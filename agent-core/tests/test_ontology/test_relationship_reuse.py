"""Tests for relationship label reuse in ontologist extraction.

Scenarios:
1. _get_ontology_summary includes known edge type labels
2. Existing edge label reused — llm_edge_type_classify NOT called
3. New edge label gets a new EdgeType with LLM-assigned semantics
4. Two steps with the same new label create only one EdgeType
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from db import Edge, EdgeType, Entity, OntologyType


async def _ctx(session):
    """Create a real AgentSpec + Run row and return a RunContext backed by them."""
    from db import AgentSpec, Run
    from spec_factory import RunContext

    spec = AgentSpec(
        name=f"test-spec-{uuid.uuid4().hex[:6]}",
        system_prompt="test",
        allowed_tools=[],
        allowed_mcp_servers={},
        max_turns=5,
    )
    session.add(spec)
    await session.flush()

    run = Run(spec_id=spec.id)
    session.add(run)
    await session.flush()

    return RunContext(
        run_id=run.id,
        task_id=None,
        spec=spec,
        agent_entity_id=uuid.uuid4(),
    )


def _resp(text: str) -> MagicMock:
    r = MagicMock()
    r.content = [MagicMock()]
    r.content[0].text = text
    return r


def _extract(label: str) -> MagicMock:
    return _resp(f"""{{
        "entities": [
            {{"name": "Alice", "properties": {{"name": "Alice", "email": "alice@x.com"}}, "type_hint": "Person"}},
            {{"name": "XCo", "properties": {{"name": "XCo", "domain": "x.com"}}, "type_hint": "Company"}}
        ],
        "relationships": [{{"src_idx": 0, "dst_idx": 1, "label": "{label}"}}]
    }}""")


_NEW_PERSON = _resp('{"decision": "NEW", "proposed": {"name": "Person", "fields": {"name": "str", "email": "str"}, "canonical_key": "email", "parent": "Entity", "description": "A person"}, "reason": "new"}')
_NEW_COMPANY = _resp('{"decision": "NEW", "proposed": {"name": "Company", "fields": {"name": "str", "domain": "str"}, "canonical_key": "domain", "parent": "Entity", "description": "A company"}, "reason": "new"}')
_EDGE_SEM = _resp('{"is_transitive": false, "is_inverse_of": null, "domain": null, "range": null}')


async def test_ontology_summary_includes_edge_types(session):
    """_get_ontology_summary should list known edge type labels."""
    from ontologist import _get_ontology_summary
    from seed import run_seed
    await run_seed(session)

    summary = await _get_ontology_summary(session)
    assert "manages" in summary       # seeded edge type
    assert "owns" in summary          # seeded edge type
    assert "Known relationship labels" in summary


async def test_new_edge_type_absent_from_summary_before_creation(session):
    """A label that does not yet exist should not appear in the summary."""
    from ontologist import _get_ontology_summary
    from seed import run_seed
    await run_seed(session)

    summary = await _get_ontology_summary(session)
    assert "novel_rel_xyz" not in summary

    session.add(EdgeType(name="novel_rel_xyz", is_transitive=False, is_inverse_of=None))
    await session.flush()

    summary2 = await _get_ontology_summary(session)
    assert "novel_rel_xyz" in summary2


async def test_existing_edge_label_reused(session):
    """When extraction returns a label matching an existing EdgeType,
    llm_edge_type_classify is NOT called and the existing EdgeType is used."""
    from ontologist import _ontologist_step_inner
    from seed import run_seed
    await run_seed(session)

    # Seed works_at so it already exists
    works_at = EdgeType(name="works_at", is_transitive=False, is_inverse_of=None)
    session.add(works_at)
    await session.flush()

    with patch("ontologist.anthropic_client") as mock_client:
        # Only 3 calls expected: extract + 2 type judges (no edge classify)
        mock_client.messages.create = AsyncMock(
            side_effect=[_extract("works_at"), _NEW_PERSON, _NEW_COMPANY]
        )
        result = await _ontologist_step_inner(
            "fetch_company_data", {}, {}, await _ctx(session), session
        )

    assert mock_client.messages.create.call_count == 3, (
        "llm_edge_type_classify should not have been called for an existing label"
    )

    # An Edge using the pre-existing EdgeType should have been created
    edge = await session.scalar(select(Edge).where(Edge.edge_type_id == works_at.id))
    assert edge is not None, "Expected an Edge using the existing works_at EdgeType"


async def test_new_edge_label_registered_with_semantics(session):
    """A new relationship label creates an EdgeType with LLM-assigned semantics."""
    from ontologist import _ontologist_step_inner
    from seed import run_seed
    await run_seed(session)

    assert await session.scalar(
        select(EdgeType).where(EdgeType.name == "subsidiary_of")
    ) is None

    edge_sem = _resp(
        '{"is_transitive": true, "is_inverse_of": "parent_of", "domain": "Company", "range": "Company"}'
    )

    with patch("ontologist.anthropic_client") as mock_client:
        mock_client.messages.create = AsyncMock(
            side_effect=[_extract("subsidiary_of"), _NEW_PERSON, _NEW_COMPANY, edge_sem]
        )
        await _ontologist_step_inner("fetch_data", {}, {}, await _ctx(session), session)

    new_et = await session.scalar(
        select(EdgeType).where(EdgeType.name == "subsidiary_of")
    )
    assert new_et is not None, "Expected subsidiary_of EdgeType to be created"
    assert new_et.is_transitive is True
    assert new_et.is_inverse_of == "parent_of"
    assert new_et.domain == "Company"


async def test_duplicate_edge_type_not_created(session):
    """Two ontologist steps with the same new label create only one EdgeType."""
    from ontologist import _ontologist_step_inner
    from seed import run_seed
    await run_seed(session)

    ctx = await _ctx(session)

    # First step — creates member_of EdgeType
    with patch("ontologist.anthropic_client") as mock_client:
        mock_client.messages.create = AsyncMock(
            side_effect=[_extract("member_of"), _NEW_PERSON, _NEW_COMPANY, _EDGE_SEM]
        )
        await _ontologist_step_inner("tool_a", {}, {}, ctx, session)

    # Resolve real type IDs for REUSE responses in the second step
    person_type = await session.scalar(select(OntologyType).where(OntologyType.name == "Person"))
    company_type = await session.scalar(select(OntologyType).where(OntologyType.name == "Company"))
    reuse_person = _resp(f'{{"decision": "REUSE", "type_id": "{person_type.id}", "reason": "same"}}')
    reuse_company = _resp(f'{{"decision": "REUSE", "type_id": "{company_type.id}", "reason": "same"}}')

    # Second step — same label, EdgeType already exists, classify NOT called
    with patch("ontologist.anthropic_client") as mock_client:
        mock_client.messages.create = AsyncMock(
            side_effect=[_extract("member_of"), reuse_person, reuse_company]
        )
        await _ontologist_step_inner("tool_b", {}, {}, ctx, session)

    rows = (
        await session.execute(select(EdgeType).where(EdgeType.name == "member_of"))
    ).scalars().all()
    assert len(rows) == 1, f"Expected 1 member_of EdgeType, got {len(rows)}"
