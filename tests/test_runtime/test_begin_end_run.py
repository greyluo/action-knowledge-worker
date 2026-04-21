import pytest
from sqlalchemy import select, text
from db import AgentSpec, OntologyType, EdgeType


async def test_tables_exist(session):
    # Verify all 9 tables are present
    for table in [
        "agent_specs", "runs", "messages", "tool_calls",
        "ontology_types", "edge_types", "entities", "edges", "ontology_events",
    ]:
        result = await session.execute(
            text(f"SELECT 1 FROM {table} LIMIT 1")
        )
        assert result is not None, f"Table {table} missing"


async def test_ontology_type_model(session):
    t = OntologyType(
        name="TestEntity",
        fields={"label": "str"},
        description="test",
        status="provisional",
    )
    session.add(t)
    await session.flush()
    result = await session.get(OntologyType, t.id)
    assert result.name == "TestEntity"


from seed import run_seed

async def test_seed_creates_types_and_spec(session):
    await run_seed(session)

    from sqlalchemy import select
    from db import OntologyType, EdgeType, AgentSpec, Entity

    types = (await session.execute(select(OntologyType))).scalars().all()
    type_names = {t.name for t in types}
    assert {"Entity", "Agent", "Run", "Task"} <= type_names

    # 6 edge types + 2 inverse pairs = 8 total
    edges = (await session.execute(select(EdgeType))).scalars().all()
    edge_names = {e.name for e in edges}
    assert {"related_to", "created_by", "executed_by", "in_service_of", "part_of", "produced"} <= edge_names
    assert "manages" in edge_names
    assert "reports_to" in edge_names

    # 1 spec + 1 Agent entity
    specs = (await session.execute(select(AgentSpec))).scalars().all()
    assert len(specs) == 1

    agents = (await session.execute(
        select(Entity).join(OntologyType, Entity.type_id == OntologyType.id)
        .where(OntologyType.name == "Agent")
    )).scalars().all()
    assert len(agents) == 1
