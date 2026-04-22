"""Tests for multi-agent delegation mechanics."""
import uuid

import pytest
from sqlalchemy import select

from db import AgentSpec, EdgeType, OntologyType, Run
from seed import run_seed
from spec_factory import RunContext, begin_run, get_agent_entity_id


async def test_topology_edge_types_seeded(session):
    await run_seed(session)
    for name in ["delegates_to", "next_in_chain", "parallel_with",
                 "loops_back_to", "handles", "fallback_to", "seeded_with"]:
        et = await session.scalar(select(EdgeType).where(EdgeType.name == name))
        assert et is not None, f"Edge type {name!r} not seeded"


async def test_handoff_entity_type_seeded(session):
    await run_seed(session)
    ot = await session.scalar(select(OntologyType).where(OntologyType.name == "Handoff"))
    assert ot is not None


@pytest.fixture
async def demo_spec_id(session):
    await run_seed(session)
    spec = await session.scalar(select(AgentSpec).where(AgentSpec.name == "demo-agent"))
    return spec.id


@pytest.mark.asyncio
async def test_begin_run_sets_parent_run_id(session, demo_spec_id):
    spec = await session.get(AgentSpec, demo_spec_id)
    agent_entity_id = await get_agent_entity_id(session, spec.id)

    # Create a real parent run so the FK constraint is satisfied
    parent_run = Run(spec_id=spec.id)
    session.add(parent_run)
    await session.flush()

    ctx = await begin_run(
        session, "child task", spec, agent_entity_id,
        parent_run_id=parent_run.id,
    )
    run = await session.get(Run, ctx.run_id)
    assert run.parent_run_id == parent_run.id
    assert ctx.parent_run_id == parent_run.id
