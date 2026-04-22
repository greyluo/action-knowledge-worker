"""Seed three demo agents (Research → Analyst → Writer) with chain topology.

Run once after the base seed:
    python seed_demo_topology.py

Safe to re-run — skips already-existing agents and edges.
"""

import asyncio
import uuid
from sqlalchemy import select
from db import AgentSpec, Edge, EdgeType, Entity, OntologyType, db_session
from seed import run_seed

DEMO_AGENTS = [
    {
        "name": "research-agent",
        "system_prompt": (
            "You are a Research Agent. Your job is to fetch raw data about companies "
            "and people using fetch_company_data and fetch_email_thread, then write "
            "structured entities to the graph. Do NOT analyze or interpret — only gather "
            "and record. When done, call delegate_task to pass your findings to the "
            "next agent in the chain. Finish with OUTCOME_SUMMARY: listing every entity you wrote."
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
            "Start by calling query_graph with your task ID to load your context. "
            "Analyze the entities you find: identify patterns, risks, and opportunities. "
            "Write your conclusions as new entities using remember_entity (type_hint='Analysis'). "
            "When done, call delegate_task to pass your analysis to the writer. "
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
            "Start by calling query_graph with your task ID to load your context. "
            "Write a concise report entity using remember_entity (type_hint='Report') that summarizes "
            "the findings for a non-technical stakeholder. "
            "Finish with OUTCOME_SUMMARY: with the report title."
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
        nxt_et = await session.scalar(select(EdgeType).where(EdgeType.name == "next_in_chain"))

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
                spec_id = existing.id
                print(f"Exists spec: {agent_def['name']} ({spec_id})")

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

            for et in [del_et, nxt_et]:
                existing_edge = await session.scalar(
                    select(Edge).where(
                        Edge.src_id == src_id,
                        Edge.dst_id == dst_id,
                        Edge.edge_type_id == et.id,
                    )
                )
                if not existing_edge:
                    session.add(Edge(src_id=src_id, dst_id=dst_id, edge_type_id=et.id))
                    print(f"  Edge: {src_name} --{et.name}--> {dst_name}")

    print("\nDemo topology seeded.")


if __name__ == "__main__":
    asyncio.run(seed_demo_topology())
