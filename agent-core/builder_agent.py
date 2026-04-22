"""Builder agent: single-call spec generator with capability model."""
import json
import logging
import uuid as _uuid

import anthropic
from sqlalchemy import select

_logger = logging.getLogger(__name__)

CAPABILITIES: dict[str, list[str]] = {
    "web_research": ["WebFetch", "WebSearch"],
    "file_analysis": ["Read", "Write", "Edit", "Glob", "Grep"],
    "shell": ["Bash"],
    "company_data": ["mcp__demo__fetch_company_data", "mcp__demo__fetch_email_thread"],
}

CAPABILITY_LABELS: dict[str, str] = {
    "web_research": "Web research",
    "file_analysis": "File analysis",
    "shell": "Shell access",
    "company_data": "Company data",
}


def capabilities_to_tools(capabilities: list[str]) -> list[str]:
    tools: list[str] = []
    for slug in capabilities:
        tools.extend(CAPABILITIES.get(slug, []))
    return tools


def tools_to_capabilities(tools: list[str]) -> list[str]:
    tool_set = set(tools)
    return [
        slug
        for slug, slug_tools in CAPABILITIES.items()
        if any(t in tool_set for t in slug_tools)
    ]


_GENERATE_SYSTEM = """You are an agent spec generator. Given a description of what an agent should do, output a JSON object.

Available capabilities:
- web_research: Fetch web pages and search the internet
- file_analysis: Read, write, and search files on disk
- shell: Run shell commands
- company_data: Fetch company profiles and email threads

Output ONLY a JSON object with these exact keys (no markdown fences, no extra text):
{"name": "<2-4 word agent name>", "system_prompt": "<2-5 sentence focused system prompt>", "capabilities": ["<slug>", ...]}

Select only the capabilities genuinely needed. Omit any not relevant to the description."""


_AGENT_CONTEXT_SYSTEM = """You extract real-world entities and the agent's relationships to them from an agent description.

Return ONLY valid JSON (no markdown, no explanation):
{
  "entities": [
    {"name": "<name>", "type": "<Company|Person|Product|Location|etc>", "properties": {"key": "value"}}
  ],
  "agent_relationships": [
    {"entity_idx": <int index into entities>, "label": "<edge type label>"}
  ]
}

Rules:
- Only extract entities with stable real-world identities (organizations, people, products, locations).
- Skip generic concepts like "data" or "tasks" — they are not trackable entities.
- agent_relationships links the AI agent itself to each entity. Use existing edge type names when they fit.
- If nothing meaningful, return {"entities": [], "agent_relationships": []}."""


async def _extract_agent_context(
    name: str,
    description: str,
    edge_type_names: list[str],
) -> tuple[list[dict], list[dict]]:
    edge_list = "\n".join(f"- {n}" for n in edge_type_names)
    prompt = (
        f"Known edge types (prefer these for labels):\n{edge_list or '(none)'}\n\n"
        f"Agent name: {name}\n"
        f"Agent description: {description}\n\n"
        "Extract:"
    )
    client = anthropic.AsyncAnthropic()
    for attempt in range(2):
        try:
            resp = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=512,
                system=_AGENT_CONTEXT_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text.strip()
            brace = raw.index("{")
            data = json.loads(raw[brace:raw.rindex("}") + 1])
            return data.get("entities", []), data.get("agent_relationships", [])
        except (ValueError, json.JSONDecodeError) as exc:
            _logger.warning("_extract_agent_context attempt %d failed: %s", attempt, exc)
    return [], []


async def sync_agent_to_ontology(
    spec_id: _uuid.UUID,
    name: str,
    description: str,
) -> None:
    """Create/update Agent entity and link it to entities referenced in the description."""
    from db import db_session, Entity, Edge, EdgeType, OntologyType  # noqa: PLC0415
    from ontologist import (  # noqa: PLC0415
        CandidateEntity, llm_type_match,
        _get_all_types, _get_canonical_key,
        _find_by_canonical, _find_by_name, _find_by_title,
    )

    try:
        async with db_session() as session:
            # 1. Get or create the Agent entity
            agent_type = await session.scalar(
                select(OntologyType).where(OntologyType.name == "Agent")
            )
            if not agent_type:
                return

            existing = await session.scalar(
                select(Entity).where(
                    Entity.type_id == agent_type.id,
                    Entity.properties["spec_id"].astext == str(spec_id),
                )
            )
            if existing:
                existing.properties = {
                    **existing.properties, "name": name, "description": description
                }
                agent_entity_id = existing.id
            else:
                agent_entity = Entity(
                    type_id=agent_type.id,
                    properties={"spec_id": str(spec_id), "name": name, "description": description},
                    source_refs=[{"source": "builder"}],
                )
                session.add(agent_entity)
                await session.flush()
                agent_entity_id = agent_entity.id

            # 2. Extract world entities + agent→entity relationships from description
            edge_type_names = [
                r for (r,) in (
                    await session.execute(select(EdgeType.name))
                ).all()
            ]
            raw_entities, agent_rels = await _extract_agent_context(
                name, description, edge_type_names
            )
            if not raw_entities:
                return

            # 3. Resolve each entity type and find-or-create the entity
            _SYSTEM_TYPES = {"Task", "Run", "Agent", "Entity"}
            existing_types = await _get_all_types(session)
            resolved_ids: list[_uuid.UUID | None] = []

            for raw_ent in raw_entities:
                type_hint = raw_ent.get("type")
                if type_hint in _SYSTEM_TYPES:
                    resolved_ids.append(None)
                    continue

                cand = CandidateEntity(
                    name=raw_ent["name"],
                    properties={**raw_ent.get("properties", {}), "name": raw_ent["name"]},
                    type_hint=type_hint,
                )

                match = await llm_type_match(cand, existing_types)
                if match.decision == "REUSE" and match.type_id:
                    type_id = _uuid.UUID(match.type_id)
                else:
                    proposed = match.proposed or {}
                    type_name = proposed.get("name") or type_hint or "Entity"
                    ot = await session.scalar(
                        select(OntologyType).where(OntologyType.name == type_name)
                    )
                    if not ot:
                        ot = OntologyType(
                            name=type_name,
                            parent_name=proposed.get("parent", "Entity"),
                            fields=proposed.get("fields", {}),
                            canonical_key=proposed.get("canonical_key"),
                            description=proposed.get("description", ""),
                            status="provisional",
                        )
                        session.add(ot)
                        await session.flush()
                        existing_types = await _get_all_types(session)
                    type_id = ot.id

                canonical = _get_canonical_key(existing_types, type_id)
                entity = None
                if canonical:
                    entity = await _find_by_canonical(session, type_id, canonical, cand.properties)
                if entity is None:
                    entity = await _find_by_name(session, type_id, cand.name)
                if entity is None and cand.properties.get("title"):
                    entity = await _find_by_title(session, type_id, cand.properties["title"])

                if entity:
                    entity.properties = {**entity.properties, **cand.properties}
                else:
                    entity = Entity(
                        type_id=type_id,
                        properties=cand.properties,
                        source_refs=[{"source": "agent_description"}],
                        created_by_agent_id=agent_entity_id,
                    )
                    session.add(entity)
                    await session.flush()

                resolved_ids.append(entity.id)

            # 4. Create Agent → entity edges using the extracted relationship labels
            for rel in agent_rels:
                idx = rel.get("entity_idx")
                label = rel.get("label") or "related_to"
                if idx is None or idx >= len(resolved_ids):
                    continue
                entity_id = resolved_ids[idx]
                if entity_id is None:
                    continue

                et = await session.scalar(select(EdgeType).where(EdgeType.name == label))
                if not et:
                    et = EdgeType(name=label, is_transitive=False)
                    session.add(et)
                    await session.flush()

                exists = await session.scalar(
                    select(Edge).where(
                        Edge.src_id == agent_entity_id,
                        Edge.dst_id == entity_id,
                        Edge.edge_type_id == et.id,
                    )
                )
                if not exists:
                    session.add(Edge(
                        src_id=agent_entity_id,
                        dst_id=entity_id,
                        edge_type_id=et.id,
                        created_by_agent_id=agent_entity_id,
                    ))
    except Exception as exc:
        _logger.exception("sync_agent_to_ontology failed for spec %s: %s", spec_id, exc)


async def generate_spec(description: str) -> dict:
    client = anthropic.AsyncAnthropic()
    for attempt in range(2):
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=_GENERATE_SYSTEM,
            messages=[{"role": "user", "content": description}],
        )
        raw = response.content[0].text.strip()
        try:
            brace = raw.index("{")
            end = raw.rindex("}") + 1
            return json.loads(raw[brace:end])
        except (ValueError, json.JSONDecodeError):
            if attempt == 1:
                raise ValueError(f"Failed to parse spec JSON after 2 attempts. Raw: {raw}")
    raise RuntimeError("unreachable")
