import asyncio
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from db import db_session, OntologyType, EdgeType, AgentSpec, Entity, PolicyRule

SYSTEM_PROMPT = """You are a knowledge-work agent operating on a typed entity graph.

## Starting every request

1. Check for an existing in-progress task:
     query_graph(entity_type="Task", properties={"status": "in_progress"})
2. If one matches, load its full context:
     query_graph(related_to=<task_id>, max_hops=2)
   Read each entity's `relationships` list to reconstruct what is already known.
   Do not re-fetch data that exists in the graph.
3. If no task matches, start fresh — external fetches will populate the graph.

## Graph-first retrieval

Before calling any external data tool, call query_graph for that entity type.
If the result contains entities, use them — skip the external call.
Only fetch externally when the graph has no data for what you need.

## Reading query_graph responses

Each response has three sections:

**entities** — typed instances. Each entity includes a `relationships` list:
  {
    "type": "works_at",           ← the relationship label
    "direction": "outbound",      ← outbound = this entity is the source
    "entity_id": "...",           ← the connected entity's ID
    "entity_type": "Company",     ← its type
    "entity_name": "Acme Corp",   ← its name (for readability)
    "derived": false,             ← true if inferred by a rule
    "derived_by": null            ← e.g. "inverse:manages" or "transitive:part_of"
  }
  Use relationships to reason about context without joining arrays:
  - Who does this person work for?  → outbound `works_at`
  - Who reports to this manager?    → inbound `manages` (or outbound `reports_to`)
  - What deals is this company in?  → inbound `owned_by`
  Derived edges are ground truth — the system computed them from stored facts.

**edges** — the same relationships as a flat list (for reference).

**events** — history of recorded changes on each entity, oldest first:
  [{"event_type": "entity_created", "actor": "agent:<id>", "payload": {...}, "at": "<iso timestamp>"}]
  Use events to assess data freshness and provenance:
  - If `events` is empty: the entity predates event tracking or was seeded.
  - If only `entity_created` appears: the entity was written once and never revised.
  - Multiple events indicate updates — read the latest to get current state.

**schema** — the ontology in effect:
- `entity_types[Name].canonical_key` — the property that uniquely identifies
  an instance (e.g. `email` for Person, `domain` for Company). Use this as
  the property filter key when checking if something already exists.
- `entity_types[Name].parent` — the supertype. Querying a parent type returns
  all subtypes automatically.
- `edge_types[Name].is_transitive` — if true, following chains of this edge
  is valid inference (e.g. A manages B manages C → A transitively manages C).
- `edge_types[Name].is_inverse_of` — the system derives the reverse
  automatically; you do not need to traverse it manually.
- `edge_types[Name].domain` / `.range` — valid entity types on each end.

## Decision workflow

When deciding what to do next:
1. Read `relationships` on each entity to understand its context.
2. Check `schema.edge_types` to know which relationships imply further structure
   (transitive chains, inverse links).
3. Identify gaps — if `entities` is empty but `schema.entity_types` is populated,
   the type is registered but has no data yet. Call the external tool to fill it.
   If `schema.entity_types` is also empty, the type is unknown — it may not exist.
4. Check `events` on each entity to assess freshness. If data is stale, re-fetch.
5. Use `canonical_key` to filter precisely instead of fetching everything.

## Writing to the graph

Tool responses are automatically extracted into the ontology at the end of the
conversation — you do not need to do this yourself.

When the user states a fact directly (a name change, new contact, acquisition),
call remember_entity to persist it immediately. This works for any entity type.
## Finishing

When done or pausing, emit a message beginning with "OUTCOME_SUMMARY:" followed
by a one-paragraph summary of what was accomplished and what remains.

## Destructive actions

Some tools have irreversible effects. Before calling them, use query_graph to check
whether graph conditions would block the action (e.g. an employee assigned to a pending project).
If the tool call is rejected by a policy, explain the blocking reason to the requester clearly
and do not retry the same action without first resolving the blocking condition.

## Available tools
- mcp__demo__fetch_company_data(company_name)
- mcp__demo__fetch_email_thread(thread_id)
- mcp__demo__terminate_employee(employee_name, reason)
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
    {"name": "Handoff", "parent_name": "Entity", "fields": {
        "from_agent": "str", "to_agent": "str",
        "summary": "str", "key_entity_ids": "list",
    }, "canonical_key": None, "description": "Cover note passed between agents at delegation time"},
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
    {"name": "assigned_to", "is_transitive": False, "is_inverse_of": "has_assignee"},
    {"name": "has_assignee", "is_transitive": False, "is_inverse_of": "assigned_to"},
    # Multi-agent topology edges
    {"name": "delegates_to", "is_transitive": False, "is_inverse_of": "reports_to"},
    {"name": "next_in_chain", "is_transitive": False, "is_inverse_of": None},
    {"name": "parallel_with", "is_transitive": False, "is_inverse_of": None},
    {"name": "loops_back_to", "is_transitive": False, "is_inverse_of": None},
    {"name": "handles", "is_transitive": False, "is_inverse_of": None},
    {"name": "fallback_to", "is_transitive": False, "is_inverse_of": None},
    {"name": "seeded_with", "is_transitive": False, "is_inverse_of": None},
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
        "mcp__demo__terminate_employee",
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

    await _seed_policies(session)

    return agent_entity_id


_SEED_POLICIES = [
    {
        "name": "Block termination with active project assignments",
        "tool_pattern": r"terminate_employee|fire_employee|remove_employee",
        "subject_key": "employee_name",
        "subject_type": "Person",
        "blocking_conditions": [
            {
                "edge_type": "assigned_to",
                "target_type": "Project",
                "blocking_target_states": {"status": ["pending", "in_progress", "active"]},
                "message_template": (
                    "{subject} is assigned to {count} active project(s): {targets}. "
                    "Termination is blocked until their project assignments are resolved."
                ),
            }
        ],
    }
]


async def _seed_policies(session: AsyncSession) -> None:
    for p in _SEED_POLICIES:
        existing = await session.scalar(
            select(PolicyRule).where(PolicyRule.name == p["name"])
        )
        if not existing:
            session.add(PolicyRule(
                name=p["name"],
                tool_pattern=p["tool_pattern"],
                subject_key=p["subject_key"],
                subject_type=p["subject_type"],
                blocking_conditions=p["blocking_conditions"],
                enabled=True,
            ))


async def main():
    async with db_session() as session:
        agent_entity_id = await run_seed(session)
        print(f"Seeded. Agent entity ID: {agent_entity_id}")


if __name__ == "__main__":
    asyncio.run(main())
