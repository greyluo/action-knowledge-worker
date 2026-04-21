"""query_graph tool — the agent's read path into the ontology."""
import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

import rules as _rules
from db import Edge, EdgeType, Entity, OntologyType, db_session


async def execute_query_graph(
    entity_type: str | None = None,
    properties: dict | None = None,
    related_to: str | None = None,
    edge_types: list[str] | None = None,
    max_hops: int = 1,
    apply_inference: bool = True,
) -> dict[str, Any]:
    async with db_session() as session:
        return await _query(
            session, entity_type, properties, related_to, edge_types, max_hops, apply_inference
        )


async def _query(
    session: AsyncSession,
    entity_type: str | None,
    properties: dict | None,
    related_to: str | None,
    edge_types: list[str] | None,
    max_hops: int,
    apply_inference: bool,
) -> dict[str, Any]:
    type_id = await _resolve_type_id(session, entity_type)
    et_ids = await _resolve_edge_type_ids(session, edge_types)

    if related_to:
        from_id = uuid.UUID(related_to)
        entity_ids = await _reachable_ids(session, from_id, et_ids, max_hops)
        entity_rows = await _fetch_entities(session, entity_ids, type_id, properties)
    else:
        entity_rows = await _filtered_entities(session, type_id, properties)
        entity_ids = {e.id for e in entity_rows}

    if not entity_ids:
        return {"entities": [], "edges": []}

    # Batch-load edge type names to avoid N+1 queries
    et_name_map = await _load_edge_type_names(session)

    stored_edges = await _edges_among(session, entity_ids, et_ids)
    entities_out = await _serialize_entities(session, entity_rows)
    edges_out = _serialize_stored_edges(stored_edges, et_name_map)

    if apply_inference and edges_out:
        edges_out = await _rules.apply_inference(session, edges_out, edge_types, max_hops)

    return {"entities": entities_out, "edges": edges_out}


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------


async def _resolve_type_id(session: AsyncSession, entity_type: str | None) -> uuid.UUID | None:
    if not entity_type:
        return None
    ot = await session.scalar(select(OntologyType).where(OntologyType.name == entity_type))
    return ot.id if ot else None


async def _resolve_edge_type_ids(
    session: AsyncSession, edge_types: list[str] | None
) -> list[uuid.UUID] | None:
    if not edge_types:
        return None
    rows = (
        await session.execute(select(EdgeType).where(EdgeType.name.in_(edge_types)))
    ).scalars().all()
    return [r.id for r in rows]


async def _load_edge_type_names(session: AsyncSession) -> dict[uuid.UUID, str]:
    """Return a mapping from EdgeType.id → EdgeType.name for all known edge types."""
    rows = (await session.execute(select(EdgeType))).scalars().all()
    return {r.id: r.name for r in rows}


# ---------------------------------------------------------------------------
# Traversal
# ---------------------------------------------------------------------------


async def _reachable_ids(
    session: AsyncSession,
    from_id: uuid.UUID,
    et_ids: list[uuid.UUID] | None,
    max_hops: int,
) -> set[uuid.UUID]:
    """Return all entity IDs reachable from from_id within max_hops (bidirectional)."""
    entity_ids: set[uuid.UUID] = {from_id}

    if max_hops == 1:
        q = select(Edge).where((Edge.src_id == from_id) | (Edge.dst_id == from_id))
        if et_ids is not None:
            q = q.where(Edge.edge_type_id.in_(et_ids))
        for e in (await session.execute(q)).scalars().all():
            entity_ids.add(e.src_id)
            entity_ids.add(e.dst_id)
        return entity_ids

    # Recursive CTE for multi-hop — UNION (set semantics) prevents cycles in the base,
    # UNION ALL in the recursive part (guarded by depth) allows expansion.
    et_clause = "AND edge_type_id = ANY(:et_ids)" if et_ids is not None else ""
    cte_sql = text(f"""
        WITH RECURSIVE reachable(entity_id, depth) AS (
            SELECT dst_id AS entity_id, 1 AS depth FROM edges
            WHERE src_id = :from_id {et_clause}
            UNION
            SELECT src_id AS entity_id, 1 AS depth FROM edges
            WHERE dst_id = :from_id {et_clause}
            UNION ALL
            SELECT
                CASE WHEN e.src_id = r.entity_id THEN e.dst_id ELSE e.src_id END,
                r.depth + 1
            FROM edges e
            JOIN reachable r ON (e.src_id = r.entity_id OR e.dst_id = r.entity_id)
            WHERE r.depth < :max_hops {et_clause}
        )
        SELECT DISTINCT entity_id FROM reachable
    """)
    params: dict[str, Any] = {"from_id": from_id, "max_hops": max_hops}
    if et_ids is not None:
        params["et_ids"] = et_ids
    rows = (await session.execute(cte_sql, params)).fetchall()
    for row in rows:
        entity_ids.add(row.entity_id)
    return entity_ids


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------


async def _filtered_entities(
    session: AsyncSession,
    type_id: uuid.UUID | None,
    properties: dict | None,
) -> list[Entity]:
    q = select(Entity)
    if type_id is not None:
        q = q.where(Entity.type_id == type_id)
    if properties:
        for k, v in properties.items():
            q = q.where(Entity.properties[k].astext == str(v))
    return list((await session.execute(q)).scalars().all())


async def _fetch_entities(
    session: AsyncSession,
    entity_ids: set[uuid.UUID],
    type_id: uuid.UUID | None,
    properties: dict | None,
) -> list[Entity]:
    if not entity_ids:
        return []
    q = select(Entity).where(Entity.id.in_(entity_ids))
    if type_id is not None:
        q = q.where(Entity.type_id == type_id)
    if properties:
        for k, v in properties.items():
            q = q.where(Entity.properties[k].astext == str(v))
    return list((await session.execute(q)).scalars().all())


async def _edges_among(
    session: AsyncSession,
    entity_ids: set[uuid.UUID],
    et_ids: list[uuid.UUID] | None,
) -> list[Edge]:
    if not entity_ids:
        return []
    q = select(Edge).where(
        Edge.src_id.in_(entity_ids),
        Edge.dst_id.in_(entity_ids),
    )
    if et_ids is not None:
        q = q.where(Edge.edge_type_id.in_(et_ids))
    return list((await session.execute(q)).scalars().all())


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


async def _serialize_entities(
    session: AsyncSession, rows: list[Entity]
) -> list[dict[str, Any]]:
    type_cache: dict[uuid.UUID, str] = {}
    out = []
    for e in rows:
        type_name = type_cache.get(e.type_id)
        if type_name is None:
            ot = await session.get(OntologyType, e.type_id)
            type_name = ot.name if ot else str(e.type_id)
            type_cache[e.type_id] = type_name
        out.append({
            "id": str(e.id),
            "type": type_name,
            "properties": e.properties,
            "source_refs": e.source_refs,
        })
    return out


def _serialize_stored_edges(
    rows: list[Edge], et_name_map: dict[uuid.UUID, str]
) -> list[dict[str, Any]]:
    """Serialize Edge ORM rows to dicts with string type names (not UUIDs)."""
    return [
        {
            "src": str(e.src_id),
            "dst": str(e.dst_id),
            "type": et_name_map.get(e.edge_type_id, str(e.edge_type_id)),
            "derived": False,
        }
        for e in rows
    ]
