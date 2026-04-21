import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from db import Edge, EdgeType, Entity


async def get_inverse_edges(
    session: AsyncSession, entity_id: uuid.UUID, edge_type_names: list[str]
) -> list[dict[str, Any]]:
    """Return synthetic inverse edges for edges involving entity_id.

    For each requested edge type name, finds its inverse_of partner and returns
    flipped edges as derived=True.
    """
    derived: list[dict[str, Any]] = []
    for name in edge_type_names:
        et = await session.scalar(select(EdgeType).where(EdgeType.name == name))
        if not et or not et.is_inverse_of:
            continue
        # Find all stored edges of the inverse type that involve entity_id
        inverse_et = await session.scalar(
            select(EdgeType).where(EdgeType.name == et.is_inverse_of)
        )
        if not inverse_et:
            continue
        # Edges where entity_id is the DST (so in the inverse, it becomes the SRC)
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
            })
    return derived


async def get_transitive_closure(
    session: AsyncSession,
    from_entity_id: uuid.UUID,
    edge_type_name: str,
    max_hops: int = 5,
) -> list[dict[str, Any]]:
    """Walk transitive edges up to max_hops, returning all reachable (src, dst) pairs."""
    et = await session.scalar(select(EdgeType).where(EdgeType.name == edge_type_name))
    if not et or not et.is_transitive:
        return []

    # Recursive CTE for transitive closure
    cte_sql = text("""
        WITH RECURSIVE closure(src_id, dst_id, depth) AS (
            SELECT src_id, dst_id, 1
            FROM edges
            WHERE edge_type_id = :edge_type_id AND src_id = :from_id
            UNION ALL
            SELECT e.src_id, e.dst_id, c.depth + 1
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
        {"src": str(row.src_id), "dst": str(row.dst_id), "depth": row.depth, "derived": row.depth > 1}
        for row in rows
    ]


async def apply_inference(
    session: AsyncSession,
    edges: list[dict[str, Any]],
    edge_type_names: list[str] | None,
    max_hops: int,
) -> list[dict[str, Any]]:
    """Given a set of stored edges, augment with derived inverse + transitive edges."""
    all_entity_ids = {uuid.UUID(e["src"]) for e in edges} | {uuid.UUID(e["dst"]) for e in edges}
    derived: list[dict[str, Any]] = []

    for entity_id in all_entity_ids:
        if edge_type_names:
            inv = await get_inverse_edges(session, entity_id, edge_type_names)
            derived.extend(inv)

        transitive_types_q = select(EdgeType).where(EdgeType.is_transitive == True)  # noqa: E712
        transitive_types = (await session.execute(transitive_types_q)).scalars().all()
        for tet in transitive_types:
            if edge_type_names and tet.name not in edge_type_names:
                continue
            trans = await get_transitive_closure(session, entity_id, tet.name, max_hops)
            derived.extend(trans)

    # Deduplicate
    seen = {(e["src"], e["dst"], e.get("type", "")) for e in edges}
    unique_derived = []
    for e in derived:
        key = (e["src"], e["dst"], e["type"])
        if key not in seen:
            seen.add(key)
            unique_derived.append(e)

    return edges + unique_derived
