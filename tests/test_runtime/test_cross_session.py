"""Cross-session continuity integration test.

Proves: a fresh session (new run_id, no chat history) can resume prior work
by querying execute_query_graph(related_to=task_id, max_hops=2), which returns
all entities created in the prior session via in_service_of edges.

Uses the main sprint_demo DB (via db_session()) — same as test_smoke.py —
because ontologist_step and execute_query_graph open their own connections
internally. Both begin_run calls also use real db_session() so Session 2 sees
Session 1's committed data.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select, delete

from db import (
    AgentSpec,
    Edge,
    Entity,
    OntologyEvent,
    OntologyType,
    Run,
    db_session,
)
from mock_tools import COMPANY_DATA
from seed import run_seed
from spec_factory import RunContext, begin_run, end_run


# ---------------------------------------------------------------------------
# LLM response helpers
# ---------------------------------------------------------------------------


def _make_llm_response(text: str) -> MagicMock:
    resp = MagicMock()
    resp.content = [MagicMock()]
    resp.content[0].text = text
    return resp


def _extract_company_response() -> MagicMock:
    return _make_llm_response("""{
  "entities": [
    {"name": "Acme Corp", "properties": {"name": "Acme Corp", "domain": "acme.com"}, "type_hint": "Company"},
    {"name": "Alice Chen", "properties": {"name": "Alice Chen", "email": "alice@acme.com"}, "type_hint": "Person"},
    {"name": "Bob Martinez", "properties": {"name": "Bob Martinez", "email": "bob@acme.com"}, "type_hint": "Person"},
    {"name": "Acme Renewal 2026", "properties": {"name": "Acme Renewal 2026", "company": "Acme Corp"}, "type_hint": "Deal"}
  ],
  "relationships": []
}""")


def _new_type_response(name: str, fields: dict, description: str) -> MagicMock:
    import json
    return _make_llm_response(json.dumps({
        "decision": "NEW",
        "proposed": {
            "name": name,
            "fields": fields,
            "parent": "Entity",
            "description": description,
        },
        "reason": "New type",
    }))


# ---------------------------------------------------------------------------
# Module-scoped fixture: seed + clean up after test
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
async def seeded():
    """Seed the main DB, yield spec/agent_entity_id, then clean up."""
    async with db_session() as session:
        agent_entity_id = await run_seed(session)
        spec = await session.scalar(select(AgentSpec).where(AgentSpec.name == "demo-agent"))
        spec_id = spec.id

    cleanup_after = datetime.now(timezone.utc)

    yield {"spec_id": spec_id, "agent_entity_id": agent_entity_id}

    # Cleanup: delete only rows created during this test (timestamp-scoped)
    async with db_session() as session:
        run_rows = (
            await session.execute(
                select(Run).where(
                    Run.spec_id == spec_id,
                    Run.started_at >= cleanup_after,
                )
            )
        ).scalars().all()
        run_ids = [r.id for r in run_rows]

        task_entity_ids = [
            r.in_service_of_task_id
            for r in run_rows
            if r.in_service_of_task_id
        ]

        if run_ids:
            await session.execute(
                delete(Edge).where(Edge.created_in_run_id.in_(run_ids))
            )
            await session.execute(
                delete(Entity).where(Entity.created_in_run_id.in_(run_ids))
            )

        if task_entity_ids:
            await session.execute(
                delete(Entity).where(Entity.id.in_(task_entity_ids))
            )

        extra_type_names = ("Person", "Company", "Deal")
        await session.execute(
            delete(OntologyType)
            .where(OntologyType.name.in_(extra_type_names))
            .where(OntologyType.status == "provisional")
        )

        actor = f"agent:{agent_entity_id}"
        await session.execute(
            delete(OntologyEvent).where(OntologyEvent.actor == actor)
        )

        if run_ids:
            await session.execute(delete(Run).where(Run.id.in_(run_ids)))


# ---------------------------------------------------------------------------
# Cross-session continuity test
# ---------------------------------------------------------------------------


@pytest.mark.slow
async def test_cross_session_continuity(seeded):
    """Fresh session resumes prior work via task subgraph query.

    Session 1: begin_run → ontologist_step (creates Company, 2 Persons, Deal) → end_run
    Session 2: begin_run with resumption keyword → same task_id returned
               execute_query_graph(related_to=task_id, max_hops=2) → all Session 1 entities found
    """
    from query_graph import execute_query_graph
    from ontologist import ontologist_step

    spec_id: uuid.UUID = seeded["spec_id"]
    agent_entity_id: uuid.UUID = seeded["agent_entity_id"]

    # -----------------------------------------------------------------------
    # Session 1 — begin_run
    # -----------------------------------------------------------------------
    async with db_session() as session:
        spec = await session.get(AgentSpec, spec_id)
        ctx1: RunContext = await begin_run(
            session, "Get information about Acme Corp", spec, agent_entity_id
        )

    assert ctx1.run_id is not None
    assert ctx1.task_id is not None

    # -----------------------------------------------------------------------
    # Session 1 — ontologist_step (mocked LLM, no real API calls)
    # -----------------------------------------------------------------------
    new_company = _new_type_response("Company", {"name": "str", "domain": "str"}, "A company")
    new_person = _new_type_response("Person", {"name": "str", "email": "str"}, "A person")
    new_deal = _new_type_response("Deal", {"name": "str", "company": "str"}, "A deal")

    with patch("ontologist.anthropic_client") as mock_client:
        mock_client.messages.create = AsyncMock(
            side_effect=[
                _extract_company_response(),  # llm_extract
                new_company,                  # judge: Acme Corp → Company
                new_person,                   # judge: Alice Chen → Person
                new_person,                   # judge: Bob Martinez → Person (type already exists)
                new_deal,                     # judge: Acme Renewal 2026 → Deal
            ]
        )
        entity_ids_session1 = await ontologist_step(
            tool_name="fetch_company_data",
            tool_input={"company_name": "Acme Corp"},
            tool_output=COMPANY_DATA["Acme Corp"],
            run_ctx=ctx1,
        )

    assert len(entity_ids_session1) >= 3, (
        f"Expected at least 3 entities from Session 1, got {len(entity_ids_session1)}"
    )

    # -----------------------------------------------------------------------
    # Session 1 — end_run (Task stays in_progress — no OUTCOME_SUMMARY)
    # -----------------------------------------------------------------------
    async with db_session() as session:
        await end_run(session, ctx1, messages=[])

    # Verify Run 1 is done and Task is still in_progress
    async with db_session() as session:
        run1 = await session.get(Run, ctx1.run_id)
        assert run1.status == "done"
        task1 = await session.get(Entity, ctx1.task_id)
        assert task1.properties["status"] == "in_progress"

    # -----------------------------------------------------------------------
    # Session 2 — fresh begin_run with resumption keyword
    # -----------------------------------------------------------------------
    async with db_session() as session:
        spec = await session.get(AgentSpec, spec_id)
        ctx2: RunContext = await begin_run(
            session,
            "where were we on the Acme Corp research",
            spec,
            agent_entity_id,
        )

    # Core continuity assertions
    assert ctx2.task_id == ctx1.task_id, (
        f"Session 2 should resume Session 1's task; "
        f"got ctx2.task_id={ctx2.task_id}, ctx1.task_id={ctx1.task_id}"
    )
    assert ctx2.run_id != ctx1.run_id, (
        "Session 2 must create a new Run, not reuse Session 1's run"
    )

    # -----------------------------------------------------------------------
    # Session 2 — query the task subgraph (read path)
    # -----------------------------------------------------------------------
    result = await execute_query_graph(
        related_to=str(ctx2.task_id),
        max_hops=2,
        apply_inference=False,
    )

    returned_entities = result["entities"]
    returned_ids = {e["id"] for e in returned_entities}

    # At least 3 business entities created in Session 1 must be present
    assert len(returned_entities) >= 3, (
        f"Expected at least 3 entities in task subgraph, got {len(returned_entities)}: "
        f"{[e.get('type') for e in returned_entities]}"
    )

    # All entity IDs from Session 1's ontologist_step must be in the result
    session1_ids = {str(eid) for eid in entity_ids_session1}
    assert session1_ids.issubset(returned_ids), (
        f"Session 1 entity IDs not fully present in task subgraph.\n"
        f"  Missing: {session1_ids - returned_ids}\n"
        f"  Returned: {returned_ids}"
    )

    # At least one entity should be recognisably a "Company" (case-insensitive)
    type_names = {e["type"].lower() for e in returned_entities}
    assert any("company" in t for t in type_names), (
        f"Expected at least one Company entity in subgraph; types found: {type_names}"
    )
