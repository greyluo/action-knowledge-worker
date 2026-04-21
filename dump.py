"""CLI dump commands: dump_graph and dump_task."""
import json
import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import (
    Edge,
    EdgeType,
    Entity,
    OntologyEvent,
    OntologyType,
    Run,
    ToolCall,
    db_session,
)
import rules as _rules


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_all_type_names(session: AsyncSession) -> dict[uuid.UUID, str]:
    rows = (await session.execute(select(OntologyType))).scalars().all()
    return {r.id: r.name for r in rows}


async def _load_all_edge_type_names(session: AsyncSession) -> dict[uuid.UUID, str]:
    rows = (await session.execute(select(EdgeType))).scalars().all()
    return {r.id: r.name for r in rows}


def _props_summary(props: dict) -> str:
    """Compact one-line summary of an entity's properties."""
    if not props:
        return "(no properties)"
    parts = []
    for k, v in props.items():
        if v is None:
            continue
        s = str(v)
        if len(s) > 40:
            s = s[:37] + "..."
        parts.append(f"{k}={s!r}")
    return "  ".join(parts) if parts else "(no properties)"


def _source_refs_summary(source_refs: list) -> str:
    if not source_refs:
        return ""
    sources = [sr.get("source", str(sr)) for sr in source_refs if isinstance(sr, dict)]
    sources += [str(sr) for sr in source_refs if not isinstance(sr, dict)]
    return ", ".join(sources)


# ---------------------------------------------------------------------------
# dump_graph
# ---------------------------------------------------------------------------


async def dump_graph(run_id: uuid.UUID) -> None:
    """Print a human-readable dump of all graph data for a given run."""
    async with db_session() as session:
        # Verify the run exists
        run = await session.get(Run, run_id)
        if run is None:
            print(f"No run found with id={run_id}")
            return

        type_name_map = await _load_all_type_names(session)
        edge_type_name_map = await _load_all_edge_type_names(session)

        # Load entities created in this run
        entities: list[Entity] = list(
            (
                await session.execute(
                    select(Entity).where(Entity.created_in_run_id == run_id).order_by(Entity.created_at)
                )
            )
            .scalars()
            .all()
        )

        # Load stored edges created in this run
        stored_edges: list[Edge] = list(
            (
                await session.execute(
                    select(Edge).where(Edge.created_in_run_id == run_id).order_by(Edge.created_at)
                )
            )
            .scalars()
            .all()
        )

        # Load ontology events for this run (actor contains run_id or entity was created in run)
        # Events don't have a run_id FK directly; we match via entities created in this run
        entity_ids_in_run = {e.id for e in entities}
        events: list[OntologyEvent] = list(
            (
                await session.execute(
                    select(OntologyEvent)
                    .where(OntologyEvent.entity_id.in_(entity_ids_in_run))
                    .order_by(OntologyEvent.created_at)
                )
            )
            .scalars()
            .all()
        ) if entity_ids_in_run else []

        # Load tool calls for this run
        tool_calls: list[ToolCall] = list(
            (
                await session.execute(
                    select(ToolCall)
                    .where(ToolCall.run_id == run_id)
                    .order_by(ToolCall.created_at)
                )
            )
            .scalars()
            .all()
        )

        # Compute inferred edges over the entities in this run
        stored_edge_dicts = [
            {
                "src": str(e.src_id),
                "dst": str(e.dst_id),
                "type": edge_type_name_map.get(e.edge_type_id, str(e.edge_type_id)),
                "derived": False,
            }
            for e in stored_edges
        ]
        all_edges_with_inference = await _rules.apply_inference(
            session,
            stored_edge_dicts,
            edge_type_names=None,
            max_hops=2,
            entity_ids=entity_ids_in_run if entity_ids_in_run else None,
        )
        inferred_edges = [e for e in all_edges_with_inference if e.get("derived")]

    # --- Print ---
    print(f"=== GRAPH DUMP: run_id={run_id} ===")
    print(f"    status={run.status}  started={run.started_at}  ended={run.ended_at}")
    print()

    # TYPES
    type_counts: dict[str, int] = defaultdict(int)
    for e in entities:
        tname = type_name_map.get(e.type_id, str(e.type_id))
        type_counts[tname] += 1

    print(f"--- TYPES ({len(type_counts)}) ---")
    if type_counts:
        max_name_len = max(len(n) for n in type_counts)
        for tname, count in sorted(type_counts.items()):
            noun = "entity" if count == 1 else "entities"
            print(f"  {tname:<{max_name_len}}  [{count} {noun}]")
    else:
        print("  (none)")
    print()

    # ENTITIES
    print("--- ENTITIES ---")
    grouped: dict[str, list[Entity]] = defaultdict(list)
    for e in entities:
        tname = type_name_map.get(e.type_id, str(e.type_id))
        grouped[tname].append(e)

    for tname in sorted(grouped.keys()):
        print(f"  [{tname}]")
        for e in grouped[tname]:
            short_id = str(e.id)[:8]
            props = _props_summary(e.properties)
            srefs = _source_refs_summary(e.source_refs)
            src_part = f"  (source: {srefs})" if srefs else ""
            print(f"    {short_id}  {props}{src_part}")
    if not entities:
        print("  (none)")
    print()

    # EDGES
    print(f"--- EDGES ({len(stored_edge_dicts)} stored, {len(inferred_edges)} inferred) ---")
    for ed in stored_edge_dicts:
        print(f"  [stored]   {ed['src'][:8]} --{ed['type']}--> {ed['dst'][:8]}")
    for ed in inferred_edges:
        depth_part = f"  depth={ed['depth']}" if "depth" in ed else ""
        print(f"  [inferred] {ed['src'][:8]} --{ed['type']}--> {ed['dst'][:8]}{depth_part}")
    if not stored_edge_dicts and not inferred_edges:
        print("  (none)")
    print()

    # ONTOLOGY EVENTS
    print(f"--- ONTOLOGY EVENTS ({len(events)}) ---")
    for ev in events:
        ts = ev.created_at.strftime("%H:%M:%S") if ev.created_at else "?"
        eid = str(ev.entity_id)[:8] if ev.entity_id else "-"
        payload_hint = ""
        if ev.payload:
            name = ev.payload.get("name") or ev.payload.get("type_name", "")
            if name:
                payload_hint = f"  ({name})"
        print(f"  {ts}  {ev.event_type:<22}  {eid}  actor:{ev.actor}{payload_hint}")
    if not events:
        print("  (none)")
    print()

    # TOOL CALLS
    print(f"--- TOOL CALLS ({len(tool_calls)}) ---")
    for tc in tool_calls:
        ts = tc.created_at.strftime("%H:%M:%S") if tc.created_at else "?"
        if tc.tool_name == "query_graph":
            filters = {k: v for k, v in tc.tool_input.items() if v is not None}
            result_count = ""
            if tc.tool_output:
                try:
                    out_text = tc.tool_output
                    if isinstance(out_text, dict):
                        content = out_text.get("content", [])
                        if content and isinstance(content, list):
                            parsed = json.loads(content[0].get("text", "{}"))
                            n = len(parsed.get("entities", []))
                            result_count = f"  [{n} results]"
                except Exception:
                    pass
            print(f"  {ts}  {tc.tool_name:<28}  {json.dumps(filters)}{result_count}")
        else:
            input_str = json.dumps(tc.tool_input)
            if len(input_str) > 60:
                input_str = input_str[:57] + "..."
            print(f"  {ts}  {tc.tool_name:<28}  {input_str}")
    if not tool_calls:
        print("  (none)")


# ---------------------------------------------------------------------------
# dump_task
# ---------------------------------------------------------------------------


async def dump_task(task_id: uuid.UUID) -> None:
    """Print a human-readable dump of a Task entity and all entities in_service_of it."""
    async with db_session() as session:
        # Find the Task entity
        task_entity = await session.get(Entity, task_id)
        if task_entity is None:
            print(f"No Task entity found with id={task_id}")
            return

        type_name_map = await _load_all_type_names(session)
        edge_type_name_map = await _load_all_edge_type_names(session)

        task_type_name = type_name_map.get(task_entity.type_id, "Unknown")

        # Find all "in_service_of" edges pointing to this task
        in_service_et = await session.scalar(
            select(EdgeType).where(EdgeType.name == "in_service_of")
        )

        service_entities: list[Entity] = []
        if in_service_et:
            edges_to_task: list[Edge] = list(
                (
                    await session.execute(
                        select(Edge).where(
                            Edge.edge_type_id == in_service_et.id,
                            Edge.dst_id == task_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            service_src_ids = {e.src_id for e in edges_to_task}

            if service_src_ids:
                service_entities = list(
                    (
                        await session.execute(
                            select(Entity)
                            .where(Entity.id.in_(service_src_ids))
                            .order_by(Entity.created_at)
                        )
                    )
                    .scalars()
                    .all()
                )

        # All entity IDs in this subgraph (task + all service entities)
        subgraph_ids = {task_id} | {e.id for e in service_entities}

        # Load all edges among the subgraph entities
        subgraph_edges: list[Edge] = []
        if subgraph_ids:
            subgraph_edges = list(
                (
                    await session.execute(
                        select(Edge).where(
                            Edge.src_id.in_(subgraph_ids),
                            Edge.dst_id.in_(subgraph_ids),
                        )
                    )
                )
                .scalars()
                .all()
            )

        # Map entity_id -> run_id for display
        run_id_by_entity: dict[uuid.UUID, uuid.UUID | None] = {
            e.id: e.created_in_run_id for e in service_entities
        }

    # --- Print ---
    print(f"=== TASK DUMP: task_id={task_id} ===")
    print()

    # Task properties
    print(f"--- TASK ({task_type_name}) ---")
    props = task_entity.properties
    title = props.get("title", "(no title)")
    status = props.get("status", "?")
    outcome = props.get("outcome_summary") or "(none)"
    print(f"  title:           {title}")
    print(f"  status:          {status}")
    print(f"  outcome_summary: {outcome}")
    for k, v in props.items():
        if k not in ("title", "status", "outcome_summary"):
            print(f"  {k}: {v}")
    print()

    # Entities in service of this task, grouped by run
    print(f"--- ENTITIES IN SERVICE OF TASK ({len(service_entities)}) ---")
    by_run: dict[str, list[Entity]] = defaultdict(list)
    for e in service_entities:
        run_label = str(e.created_in_run_id)[:8] if e.created_in_run_id else "no-run"
        by_run[run_label].append(e)

    for run_label in sorted(by_run.keys()):
        print(f"  [run:{run_label}]")
        for e in by_run[run_label]:
            tname = type_name_map.get(e.type_id, str(e.type_id))
            short_id = str(e.id)[:8]
            props_str = _props_summary(e.properties)
            print(f"    {short_id}  [{tname}]  {props_str}")
    if not service_entities:
        print("  (none)")
    print()

    # Edges within the subgraph
    print(f"--- EDGES WITHIN SUBGRAPH ({len(subgraph_edges)}) ---")
    for e in subgraph_edges:
        etype = edge_type_name_map.get(e.edge_type_id, str(e.edge_type_id))
        print(f"  {str(e.src_id)[:8]} --{etype}--> {str(e.dst_id)[:8]}")
    if not subgraph_edges:
        print("  (none)")
