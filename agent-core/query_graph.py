"""query_graph tool — the agent's read path into the ontology."""
import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

import rules as _rules
from db import Edge, EdgeType, Entity, OntologyEvent, OntologyType, db_session

_SYSTEM_TYPE_NAMES = frozenset({"Entity", "Agent", "Run", "Task"})


async def _load_type_names(
    session: AsyncSession, type_ids: set[uuid.UUID]
) -> dict[uuid.UUID, str]:
    if not type_ids:
        return {}
    rows = (
        await session.execute(select(OntologyType).where(OntologyType.id.in_(type_ids)))
    ).scalars().all()
    return {r.id: r.name for r in rows}


async def _load_type_schema(
    session: AsyncSession, type_ids: set[uuid.UUID]
) -> dict[str, dict]:
    """Return schema metadata keyed by type name for the given type IDs."""
    if not type_ids:
        return {}
    rows = (
        await session.execute(select(OntologyType).where(OntologyType.id.in_(type_ids)))
    ).scalars().all()
    return {
        r.name: {
            "parent": r.parent_name,
            "canonical_key": r.canonical_key,
            "description": r.description,
        }
        for r in rows
    }


async def _load_edge_type_schema(
    session: AsyncSession, edge_type_names: set[str]
) -> dict[str, dict]:
    """Return semantic metadata keyed by edge type name."""
    if not edge_type_names:
        return {}
    rows = (
        await session.execute(select(EdgeType).where(EdgeType.name.in_(edge_type_names)))
    ).scalars().all()
    return {
        r.name: {
            "is_transitive": r.is_transitive,
            "is_inverse_of": r.is_inverse_of,
            "domain": r.domain,
            "range": r.range_,
        }
        for r in rows
    }


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
    type_ids = await _resolve_type_ids_with_subtypes(session, entity_type)
    et_ids = await _resolve_edge_type_ids(session, edge_types)

    if related_to:
        from_id = uuid.UUID(related_to)
        entity_ids = await _reachable_ids(session, from_id, et_ids, max_hops)
        entity_rows = await _fetch_entities(session, entity_ids, type_ids, properties)
    else:
        entity_rows = await _filtered_entities(session, type_ids, properties)
        entity_ids = {e.id for e in entity_rows}

    if not entity_ids:
        # Still load schema for the requested type so the agent can distinguish
        # "no data yet" from "unknown type" — critical for gap detection.
        type_schema = {}
        if type_ids:
            type_schema = await _load_type_schema(session, set(type_ids))
        return {"entities": [], "edges": [], "schema": {"entity_types": type_schema, "edge_types": {}}}

    et_name_map = await _load_edge_type_names(session)
    type_name_map = await _load_type_names(session, {e.type_id for e in entity_rows})

    stored_edges = await _edges_among(session, entity_ids, et_ids)
    entities_out = _serialize_entities(entity_rows, type_name_map)
    edges_out = _serialize_stored_edges(stored_edges, et_name_map)

    if apply_inference and entity_ids:
        edges_out = await _rules.apply_inference(
            session, edges_out, edge_types, max_hops, entity_ids=entity_ids
        )

    all_edge_names = {e["type"] for e in edges_out}
    type_schema = await _load_type_schema(session, {e.type_id for e in entity_rows})
    edge_schema = await _load_edge_type_schema(session, all_edge_names)
    events_by_entity = await _load_entity_events(session, entity_ids)

    entities_out = _attach_relationships(entities_out, edges_out)
    entities_out = _attach_events(entities_out, events_by_entity)

    return {
        "entities": entities_out,
        "edges": edges_out,
        "schema": {
            "entity_types": type_schema,
            "edge_types": edge_schema,
        },
    }


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------


async def _resolve_type_ids_with_subtypes(
    session: AsyncSession, entity_type: str | None
) -> list[uuid.UUID] | None:
    if not entity_type:
        return None
    rows = await session.execute(
        text("""
            WITH RECURSIVE sub(id) AS (
                SELECT id FROM ontology_types WHERE name = :name
                UNION ALL
                SELECT t.id FROM ontology_types t
                JOIN sub s ON t.parent_name = (
                    SELECT name FROM ontology_types WHERE id = s.id
                )
            )
            SELECT id FROM sub
        """),
        {"name": entity_type},
    )
    ids = [row.id for row in rows]
    return ids if ids else None


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
    # NOTE: The UNION ALL recursive term allows the same node to be visited multiple
    # times on cyclic graphs (e.g. A→B→A→B…). The depth guard bounds this, but the
    # intermediate working table can still be O(branching_factor^max_hops) rows. For
    # the MVP graph size this is fine; revisit if graphs grow large.
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
    type_ids: list[uuid.UUID] | None,
    properties: dict | None,
) -> list[Entity]:
    q = select(Entity)
    if type_ids is not None:
        q = q.where(Entity.type_id.in_(type_ids))
    if properties:
        for k, v in properties.items():
            q = q.where(Entity.properties[k].astext == str(v))
    return list((await session.execute(q)).scalars().all())


async def _fetch_entities(
    session: AsyncSession,
    entity_ids: set[uuid.UUID],
    type_ids: list[uuid.UUID] | None,
    properties: dict | None,
) -> list[Entity]:
    if not entity_ids:
        return []
    q = select(Entity).where(Entity.id.in_(entity_ids))
    if type_ids is not None:
        q = q.where(Entity.type_id.in_(type_ids))
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
# Event loading
# ---------------------------------------------------------------------------


async def _load_entity_events(
    session: AsyncSession,
    entity_ids: set[uuid.UUID],
) -> dict[str, list[dict]]:
    """Return OntologyEvents grouped by entity_id string, sorted oldest-first."""
    if not entity_ids:
        return {}
    rows = (
        await session.execute(
            select(OntologyEvent)
            .where(OntologyEvent.entity_id.in_(entity_ids))
            .order_by(OntologyEvent.created_at)
        )
    ).scalars().all()
    result: dict[str, list[dict]] = {}
    for ev in rows:
        key = str(ev.entity_id)
        result.setdefault(key, []).append({
            "event_type": ev.event_type,
            "actor": ev.actor,
            "payload": ev.payload or {},
            "at": ev.created_at.isoformat(),
        })
    return result


def _attach_events(
    entities_out: list[dict],
    events_by_entity: dict[str, list[dict]],
) -> list[dict]:
    return [
        {**e, "events": events_by_entity.get(e["id"], [])}
        for e in entities_out
    ]


# ---------------------------------------------------------------------------
# Relationship attachment
# ---------------------------------------------------------------------------


def _attach_relationships(
    entities_out: list[dict],
    edges_out: list[dict],
) -> list[dict]:
    """Attach a `relationships` list to each entity dict.

    Each relationship entry describes one edge from the perspective of
    the entity it is attached to, including the peer's type and name so
    the agent can read context without joining arrays manually.
    """
    entity_type_map = {e["id"]: e["type"] for e in entities_out}
    entity_name_map = {
        e["id"]: (e.get("properties") or {}).get("name", e["id"][:8])
        for e in entities_out
    }
    adj: dict[str, list] = {e["id"]: [] for e in entities_out}

    for edge in edges_out:
        src, dst = edge["src"], edge["dst"]
        base = {
            "type": edge["type"],
            "derived": edge.get("derived", False),
            "derived_by": edge.get("derived_by"),
        }
        if src in adj:
            adj[src].append({
                **base,
                "direction": "outbound",
                "entity_id": dst,
                "entity_type": entity_type_map.get(dst),
                "entity_name": entity_name_map.get(dst),
            })
        if dst in adj:
            adj[dst].append({
                **base,
                "direction": "inbound",
                "entity_id": src,
                "entity_type": entity_type_map.get(src),
                "entity_name": entity_name_map.get(src),
            })

    return [{**e, "relationships": adj.get(e["id"], [])} for e in entities_out]


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _serialize_entities(
    rows: list[Entity], type_name_map: dict[uuid.UUID, str]
) -> list[dict[str, Any]]:
    """Serialize Entity ORM rows to dicts, resolving type names from the pre-built map."""
    return [
        {
            "id": str(e.id),
            "type": type_name_map.get(e.type_id, str(e.type_id)),
            "properties": e.properties,
            "source_refs": e.source_refs,
        }
        for e in rows
    ]


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
