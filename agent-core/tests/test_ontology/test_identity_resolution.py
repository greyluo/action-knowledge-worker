import pytest
import uuid
from sqlalchemy import select
from db import Entity, OntologyType, EdgeType, Edge

async def test_inverse_edges_returned(session):
    from rules import get_inverse_edges
    from seed import run_seed
    await run_seed(session)

    manages_et = await session.scalar(
        select(EdgeType).where(EdgeType.name == "manages")
    )
    entity_type = await session.scalar(
        select(OntologyType).where(OntologyType.name == "Entity")
    )
    a = Entity(type_id=entity_type.id, properties={"name": "Manager"})
    b = Entity(type_id=entity_type.id, properties={"name": "Report"})
    session.add_all([a, b])
    await session.flush()
    session.add(Edge(src_id=a.id, dst_id=b.id, edge_type_id=manages_et.id))
    await session.flush()

    # Query from B's perspective — should return "reports_to" A via inverse
    inverse_edges = await get_inverse_edges(session, b.id, ["reports_to"])
    assert any(e["src"] == str(b.id) and e["dst"] == str(a.id) for e in inverse_edges)
    assert all(e["derived"] for e in inverse_edges)


async def test_transitive_closure(session):
    from rules import get_transitive_closure
    from seed import run_seed
    await run_seed(session)

    manages_et = await session.scalar(select(EdgeType).where(EdgeType.name == "manages"))
    entity_type = await session.scalar(select(OntologyType).where(OntologyType.name == "Entity"))

    # Chain: A manages B manages C
    a = Entity(type_id=entity_type.id, properties={"name": "VP"})
    b = Entity(type_id=entity_type.id, properties={"name": "Manager"})
    c = Entity(type_id=entity_type.id, properties={"name": "IC"})
    session.add_all([a, b, c])
    await session.flush()
    session.add(Edge(src_id=a.id, dst_id=b.id, edge_type_id=manages_et.id))
    session.add(Edge(src_id=b.id, dst_id=c.id, edge_type_id=manages_et.id))
    await session.flush()

    # A manages C transitively at max_hops=2
    closure = await get_transitive_closure(session, a.id, "manages", max_hops=2)
    dst_ids = {e["dst"] for e in closure}
    assert str(c.id) in dst_ids
