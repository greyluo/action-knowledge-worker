import asyncio
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from db import db_session, OntologyType, EdgeType, AgentSpec, Entity

SYSTEM_PROMPT = """You are a knowledge-work agent operating on a typed entity graph.

Every user request is a Task. Before starting work, check whether this request
continues an existing task by calling:
  query_graph(entity_type="Task", properties={"status": "in_progress"})

If an in-progress task matches the user's intent, resume it: call
  query_graph(related_to=<task_id>, max_hops=2)
to retrieve every entity and decision attached to the task from prior sessions.
Do not re-derive context that is already in the graph. Summarize where you left
off before continuing.

Before taking any action that requires context (sending a message, drafting a
document, deciding who to involve), call `query_graph` to retrieve the relevant
entities and relationships. Prefer typed retrieval over re-deriving facts from
raw tool output.

When you receive tool responses, the system will automatically extract entities
into the ontology — you do not need to do this yourself. Use the entity IDs that
appear in the _ontology field of tool responses to refer to specific entities
in subsequent tool calls.

When `query_graph` returns edges marked `derived: true`, those facts come from
inference rules (inverse or transitive edges). Treat them as ground truth.

When the user provides facts about people, companies, or deals in conversation
(e.g. "Alice's email changed", "Acme Corp was acquired by Globex"), call
remember_entity before responding so the information is persisted to the graph.

When you finish (or pause) work, emit a final message beginning with
"OUTCOME_SUMMARY:" followed by a one-paragraph summary of what was accomplished
and what remains.

Available tools:
- mcp__demo__fetch_company_data(company_name)
- mcp__demo__fetch_email_thread(thread_id)
- mcp__demo__remember_entity(name, type_hint, properties)
- mcp__demo__query_graph(entity_type, properties, related_to, edge_types, max_hops, apply_inference)
"""

SEED_ENTITY_TYPES = [
    {"name": "Entity", "parent_name": None, "fields": {"id": "uuid"}, "canonical_key": None, "description": "Base entity type"},
    {"name": "Agent", "parent_name": "Entity", "fields": {"spec_id": "uuid", "name": "str"}, "canonical_key": "name", "description": "An agent running on a spec"},
    {"name": "Run", "parent_name": "Entity", "fields": {"spec_id": "uuid", "started_at": "datetime"}, "canonical_key": None, "description": "A single execution run"},
    {"name": "Task", "parent_name": "Entity", "fields": {
        "title": "str", "description": "str",
        "status": "str",
        "outcome_summary": "str",
    }, "canonical_key": None, "description": "A unit of work persisting across sessions"},
]

SEED_EDGE_TYPES = [
    {"name": "related_to", "is_transitive": False, "is_inverse_of": None},
    {"name": "created_by", "is_transitive": False, "is_inverse_of": None},
    {"name": "executed_by", "is_transitive": False, "is_inverse_of": None},
    {"name": "in_service_of", "is_transitive": False, "is_inverse_of": None},
    {"name": "part_of", "is_transitive": True, "is_inverse_of": None},
    {"name": "produced", "is_transitive": False, "is_inverse_of": None},
    {"name": "manages", "is_transitive": True, "is_inverse_of": "reports_to"},
    {"name": "reports_to", "is_transitive": False, "is_inverse_of": "manages"},
    {"name": "owns", "is_transitive": False, "is_inverse_of": "owned_by"},
    {"name": "owned_by", "is_transitive": False, "is_inverse_of": "owns"},
]


_CANONICAL_KEY_DEFAULTS = {
    "Person": "email",
    "Company": "domain",
    "Deal": "name,company",
}


async def run_seed(session: AsyncSession) -> uuid.UUID:
    """Insert seed data. Returns the agent_entity_id."""
    type_map = {}
    for t in SEED_ENTITY_TYPES:
        existing = await session.scalar(select(OntologyType).where(OntologyType.name == t["name"]))
        if not existing:
            obj = OntologyType(**t, status="stable")
            session.add(obj)
            await session.flush()
            type_map[t["name"]] = obj.id
        else:
            type_map[t["name"]] = existing.id

    # Backfill canonical_key on any provisional types that were created before
    # this column existed (Person, Company, Deal created by the ontologist).
    for type_name, ck in _CANONICAL_KEY_DEFAULTS.items():
        prov = await session.scalar(select(OntologyType).where(OntologyType.name == type_name))
        if prov and prov.canonical_key is None:
            prov.canonical_key = ck

    for e in SEED_EDGE_TYPES:
        existing = await session.scalar(select(EdgeType).where(EdgeType.name == e["name"]))
        if not existing:
            session.add(EdgeType(**e))

    _allowed_tools = [
        "mcp__demo__fetch_company_data",
        "mcp__demo__fetch_email_thread",
        "mcp__demo__remember_entity",
        "mcp__demo__query_graph",
    ]

    existing_spec = await session.scalar(select(AgentSpec).where(AgentSpec.name == "demo-agent"))
    if not existing_spec:
        spec = AgentSpec(
            name="demo-agent",
            system_prompt=SYSTEM_PROMPT,
            allowed_tools=_allowed_tools,
            max_turns=20,
        )
        session.add(spec)
        await session.flush()
        spec_id = spec.id
    else:
        # Sync prompt and tools on every start so changes take effect without a DB reset
        existing_spec.system_prompt = SYSTEM_PROMPT
        existing_spec.allowed_tools = _allowed_tools
        spec_id = existing_spec.id

    agent_type_id = type_map["Agent"]
    existing_agent = await session.scalar(
        select(Entity).where(
            Entity.type_id == agent_type_id,
            Entity.properties["spec_id"].astext == str(spec_id),
        )
    )
    if not existing_agent:
        agent_entity = Entity(
            type_id=agent_type_id,
            properties={"spec_id": str(spec_id), "name": "demo-agent"},
            source_refs=[{"source": "seed"}],
        )
        session.add(agent_entity)
        await session.flush()
        agent_entity_id = agent_entity.id
    else:
        agent_entity_id = existing_agent.id

    return agent_entity_id


async def main():
    async with db_session() as session:
        agent_entity_id = await run_seed(session)
        print(f"Seeded. Agent entity ID: {agent_entity_id}")


if __name__ == "__main__":
    asyncio.run(main())
