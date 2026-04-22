"""Tests for multi-agent delegation mechanics."""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from db import AgentSpec, Delegation, Edge, EdgeType, Entity, OntologyType, Run
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


@pytest.fixture
async def two_agent_setup(session):
    """Two agent specs with an Agent entity each and a delegates_to edge."""
    await run_seed(session)

    spec_a = AgentSpec(
        name="test-agent-a", system_prompt="A",
        allowed_tools=[], allowed_mcp_servers={}, max_turns=5,
    )
    spec_b = AgentSpec(
        name="test-agent-b", system_prompt="B",
        allowed_tools=[], allowed_mcp_servers={}, max_turns=5,
    )
    session.add(spec_a)
    session.add(spec_b)
    await session.flush()

    agent_type = await session.scalar(
        select(OntologyType).where(OntologyType.name == "Agent")
    )
    ent_a = Entity(
        type_id=agent_type.id,
        properties={"spec_id": str(spec_a.id), "name": "test-agent-a"},
        source_refs=[],
    )
    ent_b = Entity(
        type_id=agent_type.id,
        properties={"spec_id": str(spec_b.id), "name": "test-agent-b"},
        source_refs=[],
    )
    session.add(ent_a)
    session.add(ent_b)
    await session.flush()

    del_et = await session.scalar(
        select(EdgeType).where(EdgeType.name == "delegates_to")
    )
    session.add(Edge(src_id=ent_a.id, dst_id=ent_b.id, edge_type_id=del_et.id))

    task_type = await session.scalar(
        select(OntologyType).where(OntologyType.name == "Task")
    )
    task = Entity(
        type_id=task_type.id,
        properties={"title": "test", "status": "in_progress"},
        source_refs=[],
    )
    session.add(task)

    run_a = Run(spec_id=spec_a.id, in_service_of_task_id=None)
    session.add(run_a)
    await session.flush()

    return {
        "spec_a_id": spec_a.id,
        "spec_b_id": spec_b.id,
        "ent_a_id": ent_a.id,
        "ent_b_id": ent_b.id,
        "task_id": task.id,
        "run_a_id": run_a.id,
    }


@pytest.mark.asyncio
async def test_delegate_task_rejects_missing_topology_edge(two_agent_setup, session):
    setup = two_agent_setup
    run_ctx = RunContext(
        run_id=setup["run_a_id"],
        task_id=setup["task_id"],
        spec=MagicMock(id=setup["spec_a_id"], name="test-agent-a"),
        agent_entity_id=setup["ent_a_id"],
    )
    from mock_tools import _delegate_task_impl

    # Try delegating to an agent that has no edge from A
    fake_spec_id = str(uuid.uuid4())
    result = await _delegate_task_impl(
        {
            "to_agent_id": fake_spec_id,
            "task_prompt": "do something",
            "context_entity_ids": [],
            "execution_mode": "fire_and_forget",
        },
        run_ctx,
        _session=session,
    )
    assert "error" in result


@pytest.mark.asyncio
async def test_delegate_task_creates_delegation_row(two_agent_setup, session):
    setup = two_agent_setup
    run_ctx = RunContext(
        run_id=setup["run_a_id"],
        task_id=setup["task_id"],
        spec=MagicMock(id=setup["spec_a_id"], name="test-agent-a"),
        agent_entity_id=setup["ent_a_id"],
    )
    from mock_tools import _delegate_task_impl

    with patch("mock_tools._run_child_agent", new_callable=AsyncMock) as mock_spawn:
        mock_spawn.return_value = {"status": "completed", "produced_entity_ids": []}
        result = await _delegate_task_impl(
            {
                "to_agent_id": str(setup["spec_b_id"]),
                "task_prompt": "fetch company data",
                "context_entity_ids": [],
                "execution_mode": "fire_and_forget",
            },
            run_ctx,
            _session=session,
        )

    assert "delegation_id" in result
    assert result["status"] in ("running", "completed", "pending")

    delegation = await session.get(Delegation, uuid.UUID(result["delegation_id"]))
    assert delegation is not None
    assert delegation.parent_run_id == setup["run_a_id"]
    assert delegation.to_agent_spec_id == setup["spec_b_id"]
