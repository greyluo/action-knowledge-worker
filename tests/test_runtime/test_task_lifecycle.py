import uuid
import pytest
from sqlalchemy import select

from db import AgentSpec, Entity, OntologyType, Edge, EdgeType, Run
from seed import run_seed
from spec_factory import begin_run, end_run, get_agent_entity_id


async def _setup(session):
    """Seed DB and return (spec, agent_entity_id)."""
    await run_seed(session)
    spec = await session.scalar(select(AgentSpec))
    agent_entity_id = await get_agent_entity_id(session, spec.id)
    return spec, agent_entity_id


async def test_new_task_on_fresh_prompt(session):
    """begin_run with no resumption keywords creates a new Task and Run."""
    spec, agent_entity_id = await _setup(session)

    ctx = await begin_run(session, "Get information about Acme Corp", spec, agent_entity_id)

    assert ctx.task_id is not None
    assert ctx.run_id is not None

    task = await session.get(Entity, ctx.task_id)
    assert task is not None
    assert task.properties["status"] == "in_progress"

    run = await session.get(Run, ctx.run_id)
    assert run is not None
    assert run.in_service_of_task_id == ctx.task_id


async def test_new_task_has_in_service_of_edge(session):
    """begin_run creates an in_service_of edge from the Run entity to the Task entity."""
    spec, agent_entity_id = await _setup(session)

    ctx = await begin_run(session, "Research Acme Corp", spec, agent_entity_id)

    et = await session.scalar(select(EdgeType).where(EdgeType.name == "in_service_of"))
    edge = await session.scalar(
        select(Edge).where(Edge.dst_id == ctx.task_id, Edge.edge_type_id == et.id)
    )
    assert edge is not None


async def test_task_resumed_by_keyword(session):
    """begin_run with a resumption keyword reuses the most recent in_progress Task."""
    spec, agent_entity_id = await _setup(session)

    first_ctx = await begin_run(session, "Start work on Acme deal", spec, agent_entity_id)
    original_task_id = first_ctx.task_id

    resumed_ctx = await begin_run(session, "Continue where we left off", spec, agent_entity_id)

    assert resumed_ctx.task_id == original_task_id

    task_type = await session.scalar(select(OntologyType).where(OntologyType.name == "Task"))
    tasks = (
        await session.execute(
            select(Entity).where(Entity.type_id == task_type.id)
        )
    ).scalars().all()
    assert len(tasks) == 1, "Resume must not create a duplicate Task entity"


async def test_no_in_progress_task_to_resume(session):
    """begin_run with a resumption keyword but no in_progress task creates a new task."""
    spec, agent_entity_id = await _setup(session)

    ctx = await begin_run(session, "resume the research project", spec, agent_entity_id)

    assert ctx.task_id is not None
    task = await session.get(Entity, ctx.task_id)
    assert task is not None
    assert task.properties["status"] == "in_progress"


async def test_end_run_with_outcome_summary(session):
    """end_run with OUTCOME_SUMMARY sets Task status=completed and populates outcome_summary."""
    spec, agent_entity_id = await _setup(session)

    ctx = await begin_run(session, "Analyze Acme Corp", spec, agent_entity_id)
    messages = ["OUTCOME_SUMMARY: Work done. All entities extracted."]
    await end_run(session, ctx, messages)

    task = await session.get(Entity, ctx.task_id)
    assert task.properties["status"] == "completed"
    assert task.properties["outcome_summary"] == "Work done. All entities extracted."

    run = await session.get(Run, ctx.run_id)
    assert run.status == "done"


async def test_end_run_without_outcome_summary(session):
    """end_run with no OUTCOME_SUMMARY sets Task status=in_progress with a fallback summary."""
    spec, agent_entity_id = await _setup(session)

    ctx = await begin_run(session, "Analyze Acme Corp", spec, agent_entity_id)
    await end_run(session, ctx, [])

    task = await session.get(Entity, ctx.task_id)
    assert task.properties["status"] == "in_progress"
    assert task.properties["outcome_summary"]

    run = await session.get(Run, ctx.run_id)
    assert run.status == "done"


async def test_end_run_sets_ended_at(session):
    """end_run populates Run.ended_at."""
    spec, agent_entity_id = await _setup(session)

    ctx = await begin_run(session, "Analyze Acme Corp", spec, agent_entity_id)

    run_before = await session.get(Run, ctx.run_id)
    assert run_before.ended_at is None

    await end_run(session, ctx, [])

    await session.refresh(run_before)
    assert run_before.ended_at is not None
