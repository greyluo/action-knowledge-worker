import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from db import Edge, EdgeType, Entity

_TRANSITIVE_MAX_DEPTH = 5


async def get_inverse_edges(
    session: AsyncSession, entity_id: uuid.UUID, edge_type_names: list[str]
) -> list[dict[str, Any]]:
    """Return synthetic inverse edges for edges involving entity_id.

    For each name in edge_type_names, finds its is_inverse_of partner and flips
    stored edges of that partner type into derived edges of the requested type.
    """
    derived: list[dict[str, Any]] = []
    for name in edge_type_names:
        et = await session.scalar(select(EdgeType).where(EdgeType.name == name))
        if not et or not et.is_inverse_of:
            continue
        inverse_et = await session.scalar(
            select(EdgeType).where(EdgeType.name == et.is_inverse_of)
        )
        if not inverse_et:
            continue
        edges = (
            await session.execute(
                select(Edge).where(
                    Edge.edge_type_id == inverse_et.id,
                    Edge.dst_id == entity_id,
                )
            )
        ).scalars().all()
        for e in edges:
            derived.append({
                "src": str(entity_id),
                "dst": str(e.src_id),
                "type": name,
                "derived": True,
                "derived_by": f"inverse:{et.is_inverse_of}",
            })
    return derived


async def get_transitive_closure(
    session: AsyncSession,
    from_entity_id: uuid.UUID,
    edge_type_name: str,
    max_hops: int = _TRANSITIVE_MAX_DEPTH,
) -> list[dict[str, Any]]:
    """Walk transitive edges up to max_hops, returning all reachable (src, dst) pairs."""
    et = await session.scalar(select(EdgeType).where(EdgeType.name == edge_type_name))
    if not et or not et.is_transitive:
        return []

    cte_sql = text("""
        WITH RECURSIVE closure(src_id, dst_id, depth) AS (
            SELECT src_id, dst_id, 1
            FROM edges
            WHERE edge_type_id = :edge_type_id AND src_id = :from_id
            UNION ALL
            SELECT c.src_id, e.dst_id, c.depth + 1
            FROM edges e
            JOIN closure c ON e.src_id = c.dst_id
            WHERE e.edge_type_id = :edge_type_id AND c.depth < :max_hops
        )
        SELECT DISTINCT src_id, dst_id, depth FROM closure
    """)
    rows = await session.execute(
        cte_sql,
        {"edge_type_id": et.id, "from_id": from_entity_id, "max_hops": max_hops},
    )
    return [
        {
            "src": str(row.src_id),
            "dst": str(row.dst_id),
            "type": edge_type_name,
            "depth": row.depth,
            "derived": row.depth > 1,
            "derived_by": f"transitive:{edge_type_name}" if row.depth > 1 else None,
        }
        for row in rows
    ]


async def apply_inference(
    session: AsyncSession,
    edges: list[dict[str, Any]],
    edge_type_names: list[str] | None,
    max_hops: int,
    entity_ids: set[uuid.UUID] | None = None,
) -> list[dict[str, Any]]:
    """Augment stored edges with derived inverse and transitive edges.

    When edge_type_names is None, inverse derivation runs for all registered
    inverse pairs (not just the requested edge types). Transitive closure always
    uses _TRANSITIVE_MAX_DEPTH regardless of the query's max_hops, so depth-1
    queries still get full closure for transitive edge types.
    """
    edge_entity_ids = {uuid.UUID(e["src"]) for e in edges} | {uuid.UUID(e["dst"]) for e in edges}
    all_entity_ids = (entity_ids or set()) | edge_entity_ids
    derived: list[dict[str, Any]] = []

    # Determine which inverse edge types to derive. When no filter is given,
    # derive all registered inverse pairs so callers don't have to name them.
    if edge_type_names is not None:
        inv_names = edge_type_names
    else:
        all_inv_ets = (await session.execute(
            select(EdgeType).where(EdgeType.is_inverse_of.isnot(None))
        )).scalars().all()
        inv_names = [et.name for et in all_inv_ets]

    transitive_types = (await session.execute(
        select(EdgeType).where(EdgeType.is_transitive == True)  # noqa: E712
    )).scalars().all()

    for entity_id in all_entity_ids:
        if inv_names:
            inv = await get_inverse_edges(session, entity_id, inv_names)
            derived.extend(inv)

        for tet in transitive_types:
            if edge_type_names and tet.name not in edge_type_names:
                continue
            trans = await get_transitive_closure(
                session, entity_id, tet.name, max(max_hops, _TRANSITIVE_MAX_DEPTH)
            )
            derived.extend(trans)

    seen = {(e["src"], e["dst"], e.get("type", "")) for e in edges}
    unique_derived = []
    for e in derived:
        key = (e["src"], e["dst"], e["type"])
        if key not in seen:
            seen.add(key)
            unique_derived.append(e)

    return edges + unique_derived
