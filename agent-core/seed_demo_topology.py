"""Seed three demo agents (Research → Analyst → Writer) with chain topology.

Run once after the base seed:
    python seed_demo_topology.py

Safe to re-run — skips already-existing agents and edges.
"""

import asyncio
import uuid
from sqlalchemy import select
from db import AgentSpec, Edge, EdgeType, Entity, OntologyType, PolicyRule, db_session
from seed import run_seed

DEMO_AGENTS = [
    {
        "name": "library-agent",
        "system_prompt": (
            "You are a Library Agent. You manage the library catalogue and answer queries about books. "
            "Use query_graph(entity_type='Book') to look up books before fetching externally. "
            "Use remember_entity to record new books or update existing records. "
            "You are the only agent authorised to access Book entities — other agents will be blocked. "
            "Finish with OUTCOME_SUMMARY: describing what was found or updated."
        ),
        "allowed_tools": [
            "mcp__demo__query_graph",
            "mcp__demo__remember_entity",
        ],
    },
    {
        "name": "research-agent",
        "system_prompt": (
            "You are a Research Agent. Your job is to fetch raw data about companies "
            "and people using fetch_company_data and fetch_email_thread, then write "
            "structured entities to the graph. Do NOT analyze or interpret — only gather "
            "and record. When done, call delegate_task to pass your findings to the "
            "next agent in the chain. Use execution_mode=fire_and_forget. "
            "Pass the spec_id of the target agent (NOT an entity ID) as to_agent_id. "
            "Finish with OUTCOME_SUMMARY: listing every entity you wrote."
        ),
        "allowed_tools": [
            "mcp__demo__fetch_company_data",
            "mcp__demo__fetch_email_thread",
            "mcp__demo__query_graph",
            "mcp__demo__remember_entity",
            "mcp__demo__delegate_task",
        ],
    },
    {
        "name": "analyst-agent",
        "system_prompt": (
            "You are an Analyst Agent. You receive typed entities from a prior agent via the graph. "
            "Step 1: call query_graph to load your context entities. "
            "Step 2: call remember_entity EXACTLY ONCE with type_hint='Analysis' and these fields: "
            "title (string), risk_level (low/medium/high), discount_justified (bool), "
            "next_steps (list of strings), stakeholder_strategy (string). "
            "You MUST call remember_entity before delegating. "
            "Step 3: call delegate_task to pass your findings to the writer agent. "
            "In the task_prompt, include a SHORT summary (max 200 words) — do NOT copy the full graph data. "
            "Include the Analysis entity ID in context_entity_ids. "
            "Finish with OUTCOME_SUMMARY: describing your key findings."
        ),
        "allowed_tools": [
            "mcp__demo__query_graph",
            "mcp__demo__remember_entity",
            "mcp__demo__delegate_task",
        ],
    },
    {
        "name": "writer-agent",
        "system_prompt": (
            "You are a Writer Agent. You receive analysis entities from a prior agent via the graph. "
            "Step 1: call query_graph to load your context entities (use the IDs provided in your context). "
            "Step 2: call remember_entity EXACTLY ONCE with type_hint='Report' and these fields: "
            "title (string), summary (string, 2-3 paragraphs for a non-technical stakeholder), "
            "risk_rating (string), recommended_actions (list of strings). "
            "You MUST call remember_entity — do NOT just write the report as text. "
            "Step 3: finish with OUTCOME_SUMMARY: <report title>."
        ),
        "allowed_tools": [
            "mcp__demo__query_graph",
            "mcp__demo__remember_entity",
        ],
    },
]

TOPOLOGY_CHAIN = [
    ("research-agent", "analyst-agent"),
    ("analyst-agent", "writer-agent"),
]


async def seed_demo_topology():
    async with db_session() as session:
        await run_seed(session)

    async with db_session() as session:
        agent_type = await session.scalar(select(OntologyType).where(OntologyType.name == "Agent"))
        del_et = await session.scalar(select(EdgeType).where(EdgeType.name == "delegates_to"))

        spec_map: dict[str, uuid.UUID] = {}
        entity_map: dict[str, uuid.UUID] = {}

        for agent_def in DEMO_AGENTS:
            existing = await session.scalar(
                select(AgentSpec).where(AgentSpec.name == agent_def["name"])
            )
            if not existing:
                spec = AgentSpec(
                    name=agent_def["name"],
                    system_prompt=agent_def["system_prompt"],
                    allowed_tools=agent_def["allowed_tools"],
                    allowed_mcp_servers={},
                    max_turns=20,
                )
                session.add(spec)
                await session.flush()
                spec_id = spec.id
                print(f"Created spec: {agent_def['name']} ({spec_id})")
            else:
                existing.system_prompt = agent_def["system_prompt"]
                existing.allowed_tools = agent_def["allowed_tools"]
                spec_id = existing.id
                print(f"Updated spec: {agent_def['name']} ({spec_id})")

            spec_map[agent_def["name"]] = spec_id

            existing_entity = await session.scalar(
                select(Entity).where(
                    Entity.type_id == agent_type.id,
                    Entity.properties["spec_id"].astext == str(spec_id),
                )
            )
            if not existing_entity:
                ent = Entity(
                    type_id=agent_type.id,
                    properties={"spec_id": str(spec_id), "name": agent_def["name"]},
                    source_refs=[{"source": "demo_topology_seed"}],
                )
                session.add(ent)
                await session.flush()
                entity_map[agent_def["name"]] = ent.id
                print(f"  Created entity for {agent_def['name']}")
            else:
                entity_map[agent_def["name"]] = existing_entity.id

        for src_name, dst_name in TOPOLOGY_CHAIN:
            src_id = entity_map[src_name]
            dst_id = entity_map[dst_name]

            existing_edge = await session.scalar(
                select(Edge).where(
                    Edge.src_id == src_id,
                    Edge.dst_id == dst_id,
                    Edge.edge_type_id == del_et.id,
                )
            )
            if not existing_edge:
                session.add(Edge(src_id=src_id, dst_id=dst_id, edge_type_id=del_et.id))
                print(f"  Edge: {src_name} --delegates_to--> {dst_name}")

        await _seed_library_permissions(session, entity_map)

    print("\nDemo topology seeded.")


async def _seed_library_permissions(session, entity_map: dict) -> None:
    """Create Permission{resource_type=Book} and grant it to library-agent."""
    perm_type = await session.scalar(
        select(OntologyType).where(OntologyType.name == "Permission")
    )
    if not perm_type:
        print("  WARNING: Permission ontology type not found — run base seed first")
        return

    # Find or create the Book permission entity
    book_perm = await session.scalar(
        select(Entity).where(
            Entity.type_id == perm_type.id,
            Entity.properties["resource_type"].astext == "Book",
        )
    )
    if not book_perm:
        book_perm = Entity(
            type_id=perm_type.id,
            properties={"name": "Book Access", "resource_type": "Book", "access_level": "read"},
            source_refs=[{"source": "demo_topology_seed"}],
        )
        session.add(book_perm)
        await session.flush()
        print("  Created Permission{resource_type=Book}")

    # Grant library-agent access via has_permission edge
    has_perm_et = await session.scalar(
        select(EdgeType).where(EdgeType.name == "has_permission")
    )
    if not has_perm_et:
        print("  WARNING: has_permission edge type not found — run base seed first")
        return

    library_entity_id = entity_map.get("library-agent")
    if not library_entity_id:
        return

    existing = await session.scalar(
        select(Edge).where(
            Edge.src_id == library_entity_id,
            Edge.dst_id == book_perm.id,
            Edge.edge_type_id == has_perm_et.id,
        )
    )
    if not existing:
        session.add(Edge(
            src_id=library_entity_id,
            dst_id=book_perm.id,
            edge_type_id=has_perm_et.id,
        ))
        print("  Edge: library-agent --has_permission--> Permission{resource_type=Book}")


if __name__ == "__main__":
    asyncio.run(seed_demo_topology())
