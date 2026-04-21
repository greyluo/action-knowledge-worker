"""Full write+read path integration smoke test.

Uses the main sprint_demo DB (via db_session()) since ontologist_step and
execute_query_graph open their own connections internally.  LLM calls are
mocked with deterministic responses so the test is repeatable without an
API key and without network calls.

Cleanup strategy: a module-scoped fixture commits seed data, yields, then
deletes every row it created (identified by the run_id stamped on entities).
"""

import uuid
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
from mock_tools import COMPANY_DATA, EMAIL_THREADS
from seed import run_seed
from spec_factory import RunContext, begin_run, end_run


# ---------------------------------------------------------------------------
# LLM response builders — return Anthropic message mocks
# ---------------------------------------------------------------------------


def _make_llm_response(text: str) -> MagicMock:
    resp = MagicMock()
    resp.content = [MagicMock()]
    resp.content[0].text = text
    return resp


def _extract_company_response() -> MagicMock:
    """Extraction result for fetch_company_data("Acme Corp")."""
    return _make_llm_response("""{
  "entities": [
    {"name": "Acme Corp", "properties": {"name": "Acme Corp", "domain": "acme.com", "industry": "Manufacturing"}, "type_hint": "Company"},
    {"name": "Alice Chen", "properties": {"name": "Alice Chen", "email": "alice@acme.com", "role": "VP of Sales"}, "type_hint": "Person"},
    {"name": "Bob Martinez", "properties": {"name": "Bob Martinez", "email": "bob@acme.com", "role": "Account Manager"}, "type_hint": "Person"},
    {"name": "Acme Renewal 2026", "properties": {"name": "Acme Renewal 2026", "company": "Acme Corp", "value": 150000, "status": "negotiating"}, "type_hint": "Deal"}
  ],
  "relationships": [
    {"src_idx": 1, "dst_idx": 0, "label": "works_at"},
    {"src_idx": 2, "dst_idx": 0, "label": "works_at"},
    {"src_idx": 3, "dst_idx": 0, "label": "owned_by"}
  ]
}""")


def _extract_email_response() -> MagicMock:
    """Extraction result for fetch_email_thread("thread_001").

    Alice Chen uses the same email as in COMPANY_DATA — identity resolution
    must merge her into a single entity.
    """
    return _make_llm_response("""{
  "entities": [
    {"name": "Alice Chen", "properties": {"name": "Alice Chen", "email": "alice@acme.com"}, "type_hint": "Person"}
  ],
  "relationships": []
}""")


def _judge_reuse_response(type_id: str) -> MagicMock:
    return _make_llm_response(
        f'{{"decision": "REUSE", "type_id": "{type_id}", "reason": "Existing type matches"}}'
    )


# ---------------------------------------------------------------------------
# Module-scoped fixture: seed + collect run_id for cleanup
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def smoke_run_id() -> uuid.UUID:
    """Return a stable run_id used to stamp all entities created in this module.

    Not async — just generates the ID; actual DB work happens inside the tests.
    """
    return uuid.uuid4()


@pytest.fixture(scope="module")
async def seeded(smoke_run_id: uuid.UUID):
    """Seed the main DB, yield spec/agent_entity_id, then clean up."""
    async with db_session() as session:
        agent_entity_id = await run_seed(session)
        spec = await session.scalar(select(AgentSpec).where(AgentSpec.name == "demo-agent"))
        spec_id = spec.id

    yield {"spec_id": spec_id, "agent_entity_id": agent_entity_id}

    # --- cleanup: delete everything created in this test module's runs ---
    async with db_session() as session:
        # Find all runs whose spec matches (crude but safe for demo DB)
        run_rows = (
            await session.execute(select(Run).where(Run.spec_id == spec_id))
        ).scalars().all()
        run_ids = [r.id for r in run_rows]

        if run_ids:
            # Edges created in these runs
            await session.execute(
                delete(Edge).where(Edge.created_in_run_id.in_(run_ids))
            )
            # Entities created in these runs (excludes Task entity which has run_id=NULL)
            await session.execute(
                delete(Entity).where(Entity.created_in_run_id.in_(run_ids))
            )

        # Delete provisional OntologyTypes created by the ontologist during the test
        # (Person, Company, Deal — these are not in the seed set)
        extra_type_names = ("Person", "Company", "Deal")
        await session.execute(
            delete(OntologyType)
            .where(OntologyType.name.in_(extra_type_names))
            .where(OntologyType.status == "provisional")
        )

        # Delete runs themselves
        if run_ids:
            await session.execute(delete(Run).where(Run.id.in_(run_ids)))

        # Task entities created_in_run_id may be NULL — delete by title prefix
        await session.execute(
            delete(Entity).where(
                Entity.properties["title"].astext.like("Get information%")
            )
        )

        # Delete OntologyEvents (no created_in_run_id — just clear entity_created events
        # for this test run using the agent actor)
        actor = f"agent:{agent_entity_id}"
        await session.execute(
            delete(OntologyEvent).where(OntologyEvent.actor == actor)
        )


# ---------------------------------------------------------------------------
# Main smoke test
# ---------------------------------------------------------------------------


@pytest.mark.slow
async def test_full_write_then_read_path(seeded, smoke_run_id):
    """End-to-end smoke: write path (ontologist) + read path (query_graph).

    Steps:
    1. begin_run → Task entity + Run created
    2. ontologist_step with COMPANY_DATA → entities land in Postgres
    3. execute_query_graph(entity_type="Company") → Company entity found
    4. ontologist_step with EMAIL_THREADS → Alice Chen merged (one entity)
    5. execute_query_graph(entity_type="Person") → Alice appears exactly once
    6. end_run → Run.status == "done", Task.properties["status"] updated
    """
    from query_graph import execute_query_graph
    from ontologist import ontologist_step

    spec_id: uuid.UUID = seeded["spec_id"]
    agent_entity_id: uuid.UUID = seeded["agent_entity_id"]

    # --- Step 1: begin_run ---
    async with db_session() as session:
        spec = await session.get(AgentSpec, spec_id)
        ctx: RunContext = await begin_run(
            session, "Get information about Acme Corp", spec, agent_entity_id
        )

    run_id = ctx.run_id
    task_id = ctx.task_id

    assert run_id is not None
    assert task_id is not None

    # Verify Run row exists in DB
    async with db_session() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        assert run.status == "running"
        task_entity = await session.get(Entity, task_id)
        assert task_entity is not None

    # --- Steps 2 & 3: write path (company data) then read ---
    # Company/Person/Deal types may not exist yet (they're provisional, created on first
    # encounter).  The judge always returns NEW for these types; _persist_type is
    # idempotent so re-runs are safe.  llm_extract is called once; llm_type_match once
    # per extracted entity (4 total for COMPANY_DATA["Acme Corp"]).

    company_extract_resp = _extract_company_response()

    # Judge side_effect: for 4 candidates we create 3 new types and reuse Person.
    # We cannot know UUIDs ahead of time — so we'll use a custom side_effect that
    # reads from the DB after each new type is persisted. Instead, we let the judge
    # always return NEW for new types; the ontologist's _persist_type is idempotent.
    new_company = _make_llm_response(
        '{"decision": "NEW", "proposed": {"name": "Company", "fields": {"name": "str", "domain": "str"}, "parent": "Entity", "description": "A company"}, "reason": "no match"}'
    )
    new_person = _make_llm_response(
        '{"decision": "NEW", "proposed": {"name": "Person", "fields": {"name": "str", "email": "str"}, "parent": "Entity", "description": "A person"}, "reason": "no match"}'
    )
    new_deal = _make_llm_response(
        '{"decision": "NEW", "proposed": {"name": "Deal", "fields": {"name": "str", "company": "str"}, "parent": "Entity", "description": "A deal"}, "reason": "no match"}'
    )

    with patch("ontologist.anthropic_client") as mock_client:
        mock_client.messages.create = AsyncMock(
            side_effect=[
                company_extract_resp,  # llm_extract
                new_company,           # judge: Acme Corp → Company
                new_person,            # judge: Alice Chen → Person
                new_person,            # judge: Bob Martinez → Person (type already exists after flush)
                new_deal,              # judge: Acme Renewal 2026 → Deal
            ]
        )
        entity_ids_step2 = await ontologist_step(
            tool_name="fetch_company_data",
            tool_input={"company_name": "Acme Corp"},
            tool_output=COMPANY_DATA["Acme Corp"],
            run_ctx=ctx,
        )

    assert len(entity_ids_step2) >= 1, "No entities created from company data"

    # Verify provenance: every returned entity exists and has a source_ref for
    # fetch_company_data.  We do NOT assert created_in_run_id == run_id because
    # identity resolution may merge into an entity created by a prior run — the
    # merge updates source_refs but not created_in_run_id.
    async with db_session() as session:
        for eid in entity_ids_step2:
            e = await session.get(Entity, eid)
            assert e is not None, f"Entity {eid} not found"
            source_tools = {ref.get("tool") for ref in e.source_refs}
            assert "fetch_company_data" in source_tools, (
                f"Entity {eid} source_refs missing fetch_company_data: {e.source_refs}"
            )

        # Confirm at least one entity_created OntologyEvent was written (either in this
        # run or a prior idempotent run — provenance evidence is present either way).
        events = (
            await session.execute(
                select(OntologyEvent).where(OntologyEvent.event_type == "entity_created")
            )
        ).scalars().all()
        assert len(events) >= 1, "No entity_created OntologyEvents found"

    # Step 3: read path — query_graph for Company
    company_result = await execute_query_graph(entity_type="Company")
    assert len(company_result["entities"]) >= 1, "No Company entities returned by query_graph"
    for e in company_result["entities"]:
        assert "id" in e
        assert "type" in e
        assert "properties" in e
        assert "source_refs" in e

    # --- Step 4: write path (email thread, identity resolution) ---
    # We need to know the Person type_id so the judge can return REUSE for Alice.
    async with db_session() as session:
        person_type_row = await session.scalar(
            select(OntologyType).where(OntologyType.name == "Person")
        )
        assert person_type_row is not None, "Person type not found after step 2"
        person_type_id = str(person_type_row.id)

    email_extract_resp = _extract_email_response()
    reuse_person_resp = _judge_reuse_response(person_type_id)

    with patch("ontologist.anthropic_client") as mock_client:
        mock_client.messages.create = AsyncMock(
            side_effect=[
                email_extract_resp,  # llm_extract
                reuse_person_resp,   # judge: Alice Chen → REUSE Person
            ]
        )
        entity_ids_step4 = await ontologist_step(
            tool_name="fetch_email_thread",
            tool_input={"thread_id": "thread_001"},
            tool_output=EMAIL_THREADS["thread_001"],
            run_ctx=ctx,
        )

    assert len(entity_ids_step4) >= 1, "No entities resolved from email thread"

    # --- Step 5: read path — Alice Chen appears exactly once ---
    person_result = await execute_query_graph(entity_type="Person")
    assert len(person_result["entities"]) >= 1, "No Person entities returned"

    alice_entities = [
        e for e in person_result["entities"]
        if e["properties"].get("email") == "alice@acme.com"
    ]
    assert len(alice_entities) == 1, (
        f"Alice Chen should appear exactly once; found {len(alice_entities)}: {alice_entities}"
    )

    # Alice's source_refs should reference both tool calls
    alice = alice_entities[0]
    tools_referenced = {ref.get("tool") for ref in alice["source_refs"]}
    assert "fetch_company_data" in tools_referenced, (
        f"Alice source_refs missing fetch_company_data: {alice['source_refs']}"
    )
    assert "fetch_email_thread" in tools_referenced, (
        f"Alice source_refs missing fetch_email_thread: {alice['source_refs']}"
    )

    # --- Step 6: end_run ---
    async with db_session() as session:
        # Reload spec (session-scoped objects can't be reused across sessions)
        spec = await session.get(AgentSpec, spec_id)
        await end_run(session, ctx, messages=["OUTCOME_SUMMARY: Smoke test completed."])

    async with db_session() as session:
        run = await session.get(Run, run_id)
        assert run.status == "done", f"Run.status expected 'done', got {run.status!r}"
        task = await session.get(Entity, task_id)
        assert task is not None
        task_status = task.properties.get("status")
        assert task_status == "completed", (
            f"Task status unexpected: {task_status!r}"
        )
