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
