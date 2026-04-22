"""Dedup entities in the ontology graph.

Strategy:
1. For each type with a canonical key: group entities that share the same
   canonical key value(s) → merge into the richest one.
2. For remaining types without a canonical key: group by identical title/name
   → merge.
3. Merging: keep the entity with the most properties, copy in any extra
   properties from duplicates, re-point all edges, delete the rest.
"""
import asyncio
import os
import sys
import uuid
from collections import defaultdict

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db import Delegation, Edge, Entity, OntologyEvent, OntologyType, db_session


def _canonical_key(ct: OntologyType) -> list[str] | None:
    if not ct.canonical_key:
        return None
    parts = [p.strip() for p in ct.canonical_key.split(",") if p.strip()]
    return parts if parts else None


def _group_key_canonical(entity: Entity, fields: list[str]) -> tuple | None:
    props = entity.properties or {}
    vals = tuple(str(props[f]).strip().lower() for f in fields if props.get(f))
    return vals if len(vals) == len(fields) else None


def _group_key_name(entity: Entity) -> str | None:
    props = entity.properties or {}
    for k in ("name", "title"):
        v = props.get(k)
        if v and isinstance(v, str) and v.strip():
            return v.strip().lower()
    return None


def _richest(entities: list[Entity]) -> Entity:
    return max(entities, key=lambda e: len(e.properties or {}))


def _merge_props(primary: Entity, others: list[Entity]) -> dict:
    merged = dict(primary.properties or {})
    for other in others:
        for k, v in (other.properties or {}).items():
            if k not in merged or (v and not merged.get(k)):
                merged[k] = v
    return merged


async def dedup(session: AsyncSession, dry_run: bool = False) -> None:
    types = (await session.execute(select(OntologyType))).scalars().all()
    type_map = {t.id: t for t in types}

    all_entities = (await session.execute(select(Entity))).scalars().all()

    # Group by (type_id, group_key)
    groups: dict[tuple, list[Entity]] = defaultdict(list)

    for e in all_entities:
        ct = type_map.get(e.type_id)
        if not ct:
            continue

        ck_fields = _canonical_key(ct)
        if ck_fields:
            gk = _group_key_canonical(e, ck_fields)
            if gk:
                groups[(e.type_id, "ck", *gk)].append(e)
                continue
            # Canonical key absent — fall back to name/title grouping

        name_key = _group_key_name(e)
        if name_key:
            groups[(e.type_id, "name", name_key)].append(e)

    total_deleted = 0

    for key, members in groups.items():
        if len(members) < 2:
            continue

        primary = _richest(members)
        duplicates = [e for e in members if e.id != primary.id]

        merged_props = _merge_props(primary, duplicates)
        dup_ids = [d.id for d in duplicates]

        print(f"\nMerging {len(duplicates)} duplicate(s) → {primary.id}")
        print(f"  Type  : {type_map[primary.type_id].name}")
        print(f"  Keep  : {primary.id} props={list(primary.properties or {})}")
        for d in duplicates:
            print(f"  Drop  : {d.id} props={list(d.properties or {})}")

        if not dry_run:
            # Re-point edges one-by-one, deleting any that would violate the unique constraint
            for dup_id in dup_ids:
                src_edges = (await session.execute(
                    select(Edge).where(Edge.src_id == dup_id)
                )).scalars().all()
                for edge in src_edges:
                    conflict = await session.scalar(
                        select(Edge).where(
                            Edge.src_id == primary.id,
                            Edge.dst_id == edge.dst_id,
                            Edge.edge_type_id == edge.edge_type_id,
                        )
                    )
                    if conflict:
                        await session.delete(edge)
                    else:
                        edge.src_id = primary.id

                dst_edges = (await session.execute(
                    select(Edge).where(Edge.dst_id == dup_id)
                )).scalars().all()
                for edge in dst_edges:
                    conflict = await session.scalar(
                        select(Edge).where(
                            Edge.src_id == edge.src_id,
                            Edge.dst_id == primary.id,
                            Edge.edge_type_id == edge.edge_type_id,
                        )
                    )
                    if conflict:
                        await session.delete(edge)
                    else:
                        edge.dst_id = primary.id

            # Reassign OntologyEvents
            await session.execute(
                update(OntologyEvent)
                .where(OntologyEvent.entity_id.in_(dup_ids))
                .values(entity_id=primary.id)
            )

            # Re-point delegations referencing duplicates → primary
            await session.execute(
                update(Delegation)
                .where(Delegation.task_entity_id.in_(dup_ids))
                .values(task_entity_id=primary.id)
            )

            # Update primary with merged props
            primary.properties = merged_props

            # Delete duplicates
            await session.execute(delete(Entity).where(Entity.id.in_(dup_ids)))

            total_deleted += len(dup_ids)

    if dry_run:
        print("\n[dry-run] no changes written")
    else:
        await session.commit()
        print(f"\nDone — deleted {total_deleted} duplicate entities")


_SYSTEM_TYPES = {"Task", "Run", "Agent", "Entity"}


async def purge_ghosts(session: AsyncSession, dry_run: bool = False) -> None:
    """Delete non-system entities with no name/title and no canonical key value.
    These are partial extractions that can never be matched or queried."""
    types = (await session.execute(select(OntologyType))).scalars().all()
    type_map = {t.id: t for t in types}
    all_entities = (await session.execute(select(Entity))).scalars().all()

    ghost_ids = []
    for e in all_entities:
        ct = type_map.get(e.type_id)
        if not ct:
            continue
        if ct.name in _SYSTEM_TYPES:
            continue
        props = e.properties or {}

        # Has a usable name or title?
        has_name = any(
            props.get(k) and isinstance(props.get(k), str)
            for k in ("name", "title", "email", "domain")
        )
        if has_name:
            continue

        # Has canonical key value?
        ck_fields = _canonical_key(ct)
        if ck_fields and any(props.get(f) for f in ck_fields):
            continue

        ghost_ids.append(e.id)
        print(f"Ghost: {ct.name} {e.id} props={list(props.keys())}")

    if not ghost_ids:
        print("No ghost entities found")
        return

    print(f"\n{'[dry-run] Would delete' if dry_run else 'Deleting'} {len(ghost_ids)} ghost entities")

    if not dry_run:
        await session.execute(delete(Edge).where(Edge.src_id.in_(ghost_ids)))
        await session.execute(delete(Edge).where(Edge.dst_id.in_(ghost_ids)))
        await session.execute(
            update(OntologyEvent)
            .where(OntologyEvent.entity_id.in_(ghost_ids))
            .values(entity_id=None)
        )
        await session.execute(
            update(Delegation)
            .where(Delegation.task_entity_id.in_(ghost_ids))
            .values(task_entity_id=None)
        )
        await session.execute(delete(Entity).where(Entity.id.in_(ghost_ids)))
        await session.commit()


async def main() -> None:
    dry_run = "--dry-run" in sys.argv
    async with db_session() as session:
        await dedup(session, dry_run=dry_run)
    async with db_session() as session:
        await purge_ghosts(session, dry_run=dry_run)


if __name__ == "__main__":
    asyncio.run(main())
