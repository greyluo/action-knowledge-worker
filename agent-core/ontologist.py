import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

import anthropic
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import Edge, EdgeType, Entity, OntologyEvent, OntologyType, db_session
from spec_factory import RunContext

logger = logging.getLogger(__name__)

anthropic_client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

EXTRACTION_MODEL = "claude-haiku-4-5-20251001"
JUDGE_MODEL = "claude-haiku-4-5-20251001"


class CandidateEntity(BaseModel):
    name: str
    properties: dict[str, Any]
    type_hint: str | None = None


class CandidateRelationship(BaseModel):
    src_idx: int
    dst_idx: int
    label: str


class CandidateRelationshipChange(BaseModel):
    src_idx: int
    dst_idx: int
    old_label: str
    new_label: str


class ExtractionResult(BaseModel):
    entities: list[CandidateEntity]
    relationships: list[CandidateRelationship]
    removed_relationships: list[CandidateRelationship] = []
    modified_relationships: list[CandidateRelationshipChange] = []


class TypeMatchResult(BaseModel):
    decision: Literal["REUSE", "NEW"]
    type_id: str | None = None
    proposed: dict | None = None
    reason: str


@dataclass
class OntologyStepResult:
    entity_ids: list[uuid.UUID] = field(default_factory=list)
    changes: list[dict] = field(default_factory=list)   # {action, type_name, name, id}
    new_types: list[str] = field(default_factory=list)
    new_edges: list[dict] = field(default_factory=list)         # {src, label, dst}
    removed_edges: list[dict] = field(default_factory=list)     # {src, label, dst}
    modified_edges: list[dict] = field(default_factory=list)    # {src, old_label, new_label, dst}

    def to_context(self) -> str:
        if not self.entity_ids:
            return ""
        parts = []
        for c in self.changes:
            tag = "CREATED" if c["action"] == "created" else "UPDATED"
            parts.append(f'{tag} {c["type_name"]} "{c["name"]}" id={str(c["id"])[:8]}')
        for t in self.new_types:
            parts.append(f"NEW_TYPE {t} (provisional)")
        for e in self.new_edges:
            parts.append(f'EDGE "{e["src"]}" --{e["label"]}--> "{e["dst"]}"')
        for e in self.removed_edges:
            parts.append(f'REMOVED_EDGE "{e["src"]}" --{e["label"]}--> "{e["dst"]}"')
        for e in self.modified_edges:
            parts.append(f'MODIFIED_EDGE "{e["src"]}" --{e["old_label"]}-->{e["new_label"]}--> "{e["dst"]}"')
        return "; ".join(parts)


def _strip_fences(raw: str) -> str:
    """Strip markdown code fences the LLM occasionally wraps around JSON."""
    import re
    s = raw.strip()
    if s.startswith("```"):
        m = re.search(r"^```(?:json)?\s*(.*?)```", s, re.DOTALL)
        if m:
            return m.group(1).strip()
        s = s[3:]
        if s.startswith("json"):
            s = s[4:]
        return s.strip()
    return s


EXTRACT_SYSTEM = """You extract named entities and relationships from tool output JSON.
Return ONLY valid JSON matching this schema — no markdown, no explanation:
{
  "entities": [
    {"name": "<display name>", "properties": {<all known props>}, "type_hint": "<best-fit type name or null>"}
  ],
  "relationships": [
    {"src_idx": <int index into entities>, "dst_idx": <int index into entities>, "label": "<edge type name>"}
  ],
  "removed_relationships": [
    {"src_idx": <int>, "dst_idx": <int>, "label": "<edge type that no longer applies>"}
  ],
  "modified_relationships": [
    {"src_idx": <int>, "dst_idx": <int>, "old_label": "<current edge type>", "new_label": "<replacement edge type>"}
  ]
}
Rules:
- Extract every distinct named entity with a stable real-world identity: people, organizations, products, locations, events, documents, roles, concepts — anything trackable across sources.
- Include all properties present in the data (emails, IDs, URLs, titles, statuses, dates, etc.).
- Use type_hint to suggest the most specific type that fits (e.g. "Person", "Company", "Product", "Location"). Use null if uncertain.
- Do NOT extract generic values like counts, boolean flags, or raw dates as entities.
- Do NOT extract system/infrastructure entities — never set type_hint to Task, Run, Agent, or Entity.
- Do NOT extract tool names or API identifiers as entities (e.g. strings like "mcp__demo__query_graph" or anything matching the pattern mcp__*__*).
- For all relationship lists, only include pairs where both src and dst are in your entities list.
- For relationship labels, reuse an existing label from the ontology context when it fits. Only invent a new label if no existing one is semantically correct.

Relationship operation rules:
- relationships: edges that currently hold and should be created if absent.
- removed_relationships: edges that no longer apply because of a state change in the data.
  Example: book.status changes to "available" → remove the "borrows" edge from Person to Book.
  When you detect a dissolution, extract BOTH related entities so their indices are available.
- modified_relationships: edges where the relationship type should evolve rather than be dropped.
  Example: "borrows" → "has_read" preserves the Person→Book link but changes its meaning after return.
  Use modify (not remove+add) when the connection still makes semantic sense in a new form.

- If no entities, return {"entities": [], "relationships": [], "removed_relationships": [], "modified_relationships": []}.
"""


EDGE_TYPE_JUDGE_SYSTEM = """You classify a new relationship label for an ontology type system.
Return ONLY valid JSON — no markdown, no explanation:
{
  "is_transitive": <bool>,
  "is_inverse_of": "<natural inverse edge label, or null>",
  "domain": "<entity type name valid as source, or null if unconstrained>",
  "range": "<entity type name valid as target, or null if unconstrained>"
}
Guidelines:
- is_transitive: true when A→B and B→C implies A→C (e.g. part_of, located_in, manages, subsidiary_of, member_of).
- is_inverse_of: the natural inverse label if one exists (e.g. manages↔reports_to, owns↔owned_by, employs↔employed_by, parent_of↔child_of). Use null if no natural inverse.
- domain/range: only specify when the edge is meaningfully constrained to a known type (e.g. manages: domain=Person, range=Person). Use null when the edge makes sense across entity types.
"""

EDGE_NORMALIZE_SYSTEM = """You decide whether a new relationship label means the same thing as an existing edge type.
Return ONLY valid JSON — no markdown, no explanation:
{"canonical": "<exact existing label if semantically equivalent, else null>"}

Examples of equivalent pairs:
- "works_at" / "works_for" / "employed_by" → same meaning
- "part_of" / "belongs_to" → same meaning
- "located_in" / "based_in" → same meaning

Return null if the new label represents a genuinely different relationship.
"""


async def llm_extract(tool_output: Any, ontology_summary: str) -> ExtractionResult:
    prompt = f"""Existing ontology context:
{ontology_summary}

Tool output to extract entities from:
{json.dumps(tool_output, default=str)[:4000]}

Return the extraction JSON:"""

    raw = ""
    for attempt in range(2):
        try:
            resp = await anthropic_client.messages.create(
                model=EXTRACTION_MODEL,
                max_tokens=1024,
                system=EXTRACT_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text
            return ExtractionResult.model_validate_json(_strip_fences(raw))
        except (ValidationError, json.JSONDecodeError, IndexError) as e:
            logger.warning("llm_extract parse failure attempt %d: %s | raw=%r", attempt, e, raw)
            if attempt == 1:
                return ExtractionResult(entities=[], relationships=[])

    return ExtractionResult(entities=[], relationships=[])


JUDGE_SYSTEM = """You classify a candidate entity against an existing type system.
Return ONLY valid JSON — no markdown, no explanation:
  {"decision": "REUSE", "type_id": "<uuid>", "reason": "..."}
  OR
  {"decision": "NEW", "proposed": {"name": "...", "fields": {...}, "canonical_key": "<field_name or field1,field2 or null>", "parent": "Entity", "description": "..."}, "reason": "..."}

canonical_key: the field (or comma-separated fields) that uniquely identifies an instance of this type (e.g. "email" for Person, "domain" for Company). Use null if no single field is a reliable unique identifier.
Prefer REUSE if any existing type fits. Prefer extending an existing type's properties over creating a new type with near-identical shape.
"""


async def llm_type_match(candidate: CandidateEntity, existing_types: list[dict]) -> TypeMatchResult:
    type_list = "\n".join(
        f'- id={t["id"]} name={t["name"]} fields={t["fields"]} desc={t.get("description", "")}'
        for t in existing_types
    )
    prompt = f"""Existing types:
{type_list or "(none yet)"}

Candidate entity:
name: {candidate.name}
type_hint: {candidate.type_hint}
properties: {json.dumps(candidate.properties, default=str)}

Classify this candidate:"""

    raw = ""
    for attempt in range(2):
        try:
            resp = await anthropic_client.messages.create(
                model=JUDGE_MODEL,
                max_tokens=512,
                system=JUDGE_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text
            return TypeMatchResult.model_validate_json(_strip_fences(raw))
        except (ValidationError, json.JSONDecodeError, IndexError) as e:
            logger.warning("llm_type_match parse failure attempt %d: %s | raw=%r", attempt, e, raw)
            if attempt == 1:
                return TypeMatchResult(
                    decision="NEW",
                    proposed={
                        "name": candidate.type_hint or candidate.name.split()[0],
                        "fields": {k: type(v).__name__ for k, v in candidate.properties.items()},
                        "parent": "Entity",
                        "description": f"Auto-proposed from candidate: {candidate.name}",
                    },
                    reason="Parse failure fallback",
                )

    return TypeMatchResult(decision="NEW", proposed={}, reason="Fallback")


async def llm_edge_type_classify(label: str, existing_types: list[dict]) -> dict:
    type_list = "\n".join(f'- {t["name"]}' for t in existing_types)
    prompt = f"""Known entity types:
{type_list or "(none yet)"}

New edge label to classify: "{label}"

Return the edge semantics JSON:"""

    raw = ""
    for attempt in range(2):
        try:
            resp = await anthropic_client.messages.create(
                model=JUDGE_MODEL,
                max_tokens=256,
                system=EDGE_TYPE_JUDGE_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text
            data = json.loads(_strip_fences(raw))
            return {
                "is_transitive": bool(data.get("is_transitive", False)),
                "is_inverse_of": data.get("is_inverse_of") or None,
                "domain": data.get("domain") or None,
                "range_": data.get("range") or None,
            }
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.warning("llm_edge_type_classify parse failure attempt %d: %s | raw=%r", attempt, e, raw)
    return {"is_transitive": False, "is_inverse_of": None, "domain": None, "range_": None}


async def llm_edge_type_normalize(label: str, existing_types: list[dict]) -> str | None:
    """Return an existing canonical edge type name if label is semantically equivalent, else None."""
    if not existing_types:
        return None
    type_list = "\n".join(f'- {t["name"]}' for t in existing_types)
    prompt = f"""Existing edge types:
{type_list}

New label: "{label}"

Return JSON:"""
    existing_names = {t["name"] for t in existing_types}
    for attempt in range(2):
        try:
            resp = await anthropic_client.messages.create(
                model=JUDGE_MODEL,
                max_tokens=64,
                system=EDGE_NORMALIZE_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            data = json.loads(_strip_fences(resp.content[0].text))
            canonical = data.get("canonical")
            if canonical and canonical in existing_names:
                return canonical
            return None
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.warning("llm_edge_type_normalize parse failure attempt %d: %s", attempt, e)
    return None


def make_ontologist_hook(run_ctx: RunContext):
    """Returns a PostToolUse hook callback closing over run_ctx.

    SDK hook signature: (hook_input: PostToolUseHookInput, session_id: str | None, hook_context: HookContext)
    PostToolUseHookInput fields: tool_name, tool_input, tool_response, tool_use_id
    """

    async def ontologist_hook(hook_input, session_id, hook_context) -> dict:
        tool_name = hook_input.get("tool_name", "") if isinstance(hook_input, dict) else getattr(hook_input, "tool_name", "")
        tool_input = hook_input.get("tool_input", {}) if isinstance(hook_input, dict) else getattr(hook_input, "tool_input", {})
        tool_output = hook_input.get("tool_response", None) if isinstance(hook_input, dict) else getattr(hook_input, "tool_response", None)

        if tool_output is None:
            return {}

        try:
            result = await ontologist_step(tool_name, tool_input or {}, tool_output, run_ctx)
        except Exception as e:
            logger.exception("ontologist_step failed for tool %s: %s", tool_name, e)
            return {}

        if result.entity_ids:
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": json.dumps({
                        "_ontology": {
                            "entity_ids": [str(i) for i in result.entity_ids],
                            "changes": result.to_context(),
                        }
                    }),
                }
            }
        return {}

    return ontologist_hook


async def ontologist_step(
    tool_name: str,
    tool_input: dict,
    tool_output: Any,
    run_ctx: RunContext,
) -> OntologyStepResult:
    async with db_session() as session:
        return await _ontologist_step_inner(tool_name, tool_input, tool_output, run_ctx, session)



_REMEMBER_ENTITY_TOOLS = {"remember_entity", "mcp__demo__remember_entity"}
_SKIP_TOOLS = {"query_graph", "mcp__demo__query_graph"}

_TOOL_NAME_RE = re.compile(r"^mcp__\w+__\w+$")


async def _ontologist_step_inner(
    tool_name: str,
    tool_input: dict,
    tool_output: Any,
    run_ctx: RunContext,
    session: AsyncSession,
) -> OntologyStepResult:
    if tool_name in _SKIP_TOOLS:
        return OntologyStepResult()

    ontology_summary = await _get_ontology_summary(session)

    if tool_name in _REMEMBER_ENTITY_TOOLS:
        # Use tool_input as the source document so llm_extract can infer
        # relationships from properties (e.g. employer → works_at edge).
        # Fall back to single structured entity if LLM finds nothing.
        extraction = await llm_extract(tool_input, ontology_summary)
        if not extraction.entities:
            extraction = ExtractionResult(
                entities=[CandidateEntity(
                    name=tool_input.get("name", ""),
                    type_hint=tool_input.get("type_hint"),
                    properties=tool_input.get("properties") or {},
                )],
                relationships=[],
            )
        # Guarantee the primary entity has name in properties — the top-level
        # "name" arg from remember_entity isn't always carried into properties
        # by llm_extract, breaking future name-based lookups.
        primary_name = tool_input.get("name")
        if primary_name and extraction.entities:
            first = extraction.entities[0]
            if not first.properties.get("name"):
                first.properties = {**first.properties, "name": primary_name}
    else:
        extraction = await llm_extract(tool_output, ontology_summary)

    if not extraction.entities:
        return OntologyStepResult()

    _SYSTEM_TYPE_NAMES = {"Task", "Run", "Agent", "Entity"}

    existing_types = await _get_all_types(session)
    result = OntologyStepResult()
    resolved_ids = result.entity_ids  # alias — same list, index used for relationship resolution
    resolved_names: dict[uuid.UUID, str] = {}

    for cand in extraction.entities:
        if cand.type_hint in _SYSTEM_TYPE_NAMES:
            logger.debug("Skipping candidate %r with system type_hint %r", cand.name, cand.type_hint)
            continue
        if _TOOL_NAME_RE.match(cand.name):
            logger.debug("Skipping candidate %r — looks like a tool name", cand.name)
            continue
        match = await llm_type_match(cand, existing_types)

        if match.decision == "REUSE" and match.type_id:
            type_id = uuid.UUID(match.type_id)
        else:
            type_id, type_created = await _persist_type(session, match.proposed or {}, run_ctx)
            existing_types = await _get_all_types(session)
            if type_created:
                result.new_types.append(match.proposed.get("name", "Unknown") if match.proposed else "Unknown")

        type_name = next((t["name"] for t in existing_types if t["id"] == str(type_id)), str(type_id)[:8])

        canonical = _get_canonical_key(existing_types, type_id)
        # If this type has a canonical key but the extracted entity is missing all
        # canonical fields, skip it — we cannot dedup it and would create a ghost.
        # Exception: remember_entity is an explicit agent instruction, so fall through
        # to name-based dedup rather than dropping the entity entirely.
        if canonical and tool_name not in _REMEMBER_ENTITY_TOOLS:
            ck_fields = canonical if isinstance(canonical, list) else [canonical]
            has_any_ck = any(cand.properties.get(f) for f in ck_fields)
            if not has_any_ck:
                logger.debug(
                    "Skipping %r (%s): missing canonical key fields %s",
                    cand.name, type_name, ck_fields,
                )
                continue

        existing = None
        if canonical:
            existing = await _find_by_canonical(session, type_id, canonical, cand.properties)
        if existing is None and cand.properties.get("name"):
            existing = await _find_by_name(session, type_id, cand.properties["name"])
        if existing is None and cand.properties.get("title"):
            existing = await _find_by_title(session, type_id, cand.properties["title"])
        if existing is None:
            existing = await _find_by_any_string_overlap(session, type_id, cand.properties)
        if existing:
            existing.properties = {**existing.properties, **cand.properties}
            existing.source_refs = existing.source_refs + [
                {"tool": tool_name, "input": str(tool_input)[:200]}
            ]
            resolved_ids.append(existing.id)
            resolved_names[existing.id] = cand.name
            result.changes.append({"action": "updated", "type_name": type_name, "name": cand.name, "id": existing.id})
            continue

        entity = Entity(
            type_id=type_id,
            properties=cand.properties,
            source_refs=[{"tool": tool_name, "input": str(tool_input)[:200]}],
            created_by_agent_id=run_ctx.agent_entity_id,
            created_in_run_id=run_ctx.run_id,
        )
        session.add(entity)
        await session.flush()
        resolved_ids.append(entity.id)
        resolved_names[entity.id] = cand.name
        result.changes.append({"action": "created", "type_name": type_name, "name": cand.name, "id": entity.id})

        session.add(OntologyEvent(
            event_type="entity_created",
            actor=f"agent:{run_ctx.agent_entity_id}",
            entity_id=entity.id,
            payload={"type_id": str(type_id), "name": cand.name},
        ))


    type_id_to_name = {t["id"]: t["name"] for t in existing_types}

    for rel in extraction.relationships:
        if rel.src_idx < len(resolved_ids) and rel.dst_idx < len(resolved_ids):
            et = await _resolve_edge_type(session, rel.label, run_ctx, existing_types)
            if et:
                src_id = resolved_ids[rel.src_idx]
                dst_id = resolved_ids[rel.dst_idx]
                if et.domain or et.range_:
                    src_ent = await session.get(Entity, src_id)
                    dst_ent = await session.get(Entity, dst_id)
                    if et.domain and src_ent:
                        src_type = type_id_to_name.get(str(src_ent.type_id))
                        if src_type and src_type != et.domain:
                            logger.warning("Edge %s domain violation: src=%s expected=%s", rel.label, src_type, et.domain)
                    if et.range_ and dst_ent:
                        dst_type = type_id_to_name.get(str(dst_ent.type_id))
                        if dst_type and dst_type != et.range_:
                            logger.warning("Edge %s range violation: dst=%s expected=%s", rel.label, dst_type, et.range_)
                # Check exact match first
                exists = await session.scalar(
                    select(Edge).where(
                        Edge.src_id == src_id,
                        Edge.dst_id == dst_id,
                        Edge.edge_type_id == et.id,
                    )
                )
                if not exists:
                    # Also skip if a semantically equivalent edge already exists between this pair
                    existing_pair_edges = (
                        await session.execute(
                            select(Edge, EdgeType)
                            .join(EdgeType, Edge.edge_type_id == EdgeType.id)
                            .where(Edge.src_id == src_id, Edge.dst_id == dst_id)
                        )
                    ).all()
                    if existing_pair_edges:
                        existing_type_names = [{"name": etype.name} for _, etype in existing_pair_edges]
                        canonical = await llm_edge_type_normalize(et.name, existing_type_names)
                        if canonical:
                            logger.info(
                                "Skipping edge %r: semantically equivalent to existing %r between %s→%s",
                                et.name, canonical, str(src_id)[:8], str(dst_id)[:8],
                            )
                            exists = True
                if not exists:
                    session.add(Edge(
                        src_id=src_id,
                        dst_id=dst_id,
                        edge_type_id=et.id,
                        created_by_agent_id=run_ctx.agent_entity_id,
                        created_in_run_id=run_ctx.run_id,
                    ))
                    src_name = resolved_names.get(src_id, str(src_id)[:8])
                    dst_name = resolved_names.get(dst_id, str(dst_id)[:8])
                    result.new_edges.append({"src": src_name, "label": rel.label, "dst": dst_name})

    for rel in extraction.removed_relationships:
        if rel.src_idx < len(resolved_ids) and rel.dst_idx < len(resolved_ids):
            src_id = resolved_ids[rel.src_idx]
            dst_id = resolved_ids[rel.dst_idx]
            et = await session.scalar(select(EdgeType).where(EdgeType.name == rel.label))
            if et:
                edge = await session.scalar(
                    select(Edge).where(
                        Edge.src_id == src_id,
                        Edge.dst_id == dst_id,
                        Edge.edge_type_id == et.id,
                    )
                )
                if edge:
                    await session.delete(edge)
                    src_name = resolved_names.get(src_id, str(src_id)[:8])
                    dst_name = resolved_names.get(dst_id, str(dst_id)[:8])
                    result.removed_edges.append({"src": src_name, "label": rel.label, "dst": dst_name})
                    session.add(OntologyEvent(
                        event_type="edge_removed",
                        actor=f"agent:{run_ctx.agent_entity_id}",
                        entity_id=src_id,
                        payload={"label": rel.label, "dst_id": str(dst_id)},
                    ))

    for rel in extraction.modified_relationships:
        if rel.src_idx < len(resolved_ids) and rel.dst_idx < len(resolved_ids):
            src_id = resolved_ids[rel.src_idx]
            dst_id = resolved_ids[rel.dst_idx]
            old_et = await session.scalar(select(EdgeType).where(EdgeType.name == rel.old_label))
            new_et = await _resolve_edge_type(session, rel.new_label, run_ctx, existing_types)
            if old_et and new_et:
                edge = await session.scalar(
                    select(Edge).where(
                        Edge.src_id == src_id,
                        Edge.dst_id == dst_id,
                        Edge.edge_type_id == old_et.id,
                    )
                )
                if edge:
                    edge.edge_type_id = new_et.id
                    src_name = resolved_names.get(src_id, str(src_id)[:8])
                    dst_name = resolved_names.get(dst_id, str(dst_id)[:8])
                    result.modified_edges.append({
                        "src": src_name, "old_label": rel.old_label,
                        "new_label": rel.new_label, "dst": dst_name,
                    })
                    session.add(OntologyEvent(
                        event_type="edge_modified",
                        actor=f"agent:{run_ctx.agent_entity_id}",
                        entity_id=src_id,
                        payload={"old_label": rel.old_label, "new_label": rel.new_label, "dst_id": str(dst_id)},
                    ))

    return result


async def _get_ontology_summary(session: AsyncSession) -> str:
    types = (await session.execute(select(OntologyType))).scalars().all()
    edge_types = (await session.execute(select(EdgeType))).scalars().all()
    type_lines = [f"- {t.name}: fields={t.fields}" for t in types]
    edge_lines = [f"- {et.name}" for et in edge_types]
    parts = ["Entity types:"] + type_lines + ["", "Known relationship labels (prefer these):"] + edge_lines
    return "\n".join(parts)


async def _get_all_types(session: AsyncSession) -> list[dict]:
    types = (await session.execute(select(OntologyType))).scalars().all()
    return [
        {
            "id": str(t.id),
            "name": t.name,
            "parent_name": t.parent_name,
            "fields": t.fields,
            "canonical_key": t.canonical_key,
            "description": t.description,
        }
        for t in types
    ]


async def _persist_type(session: AsyncSession, proposed: dict, run_ctx: RunContext) -> tuple[uuid.UUID, bool]:
    name = proposed.get("name", "Unknown")
    existing = await session.scalar(select(OntologyType).where(OntologyType.name == name))
    if existing:
        return existing.id, False
    ot = OntologyType(
        name=name,
        parent_name=proposed.get("parent", "Entity"),
        fields=proposed.get("fields", {}),
        canonical_key=proposed.get("canonical_key"),
        description=proposed.get("description", ""),
        status="provisional",
    )
    session.add(ot)
    await session.flush()
    session.add(OntologyEvent(
        event_type="type_created",
        actor=f"agent:{run_ctx.agent_entity_id}",
        payload={"name": name, "proposed": proposed},
    ))
    return ot.id, True


def _get_canonical_key(types: list[dict], type_id: uuid.UUID) -> str | list[str] | None:
    by_id = {t["id"]: t for t in types}
    by_name = {t["name"]: t for t in types}

    t = by_id.get(str(type_id))
    while t:
        ck = t.get("canonical_key")
        if ck:
            parts = [p.strip() for p in ck.split(",") if p.strip()]
            return parts if len(parts) > 1 else parts[0]
        parent_name = t.get("parent_name")
        t = by_name.get(parent_name) if parent_name else None
    return None


async def _find_by_canonical(
    session: AsyncSession, type_id: uuid.UUID, canonical: str | list[str], properties: dict
) -> Entity | None:
    if isinstance(canonical, str):
        val = properties.get(canonical)
        if not val:
            return None
        return await session.scalar(
            select(Entity).where(
                Entity.type_id == type_id,
                Entity.properties[canonical].astext == str(val),
            )
        )
    fields = canonical
    query = select(Entity).where(Entity.type_id == type_id)
    for f in fields:
        val = properties.get(f)
        if not val:
            return None
        query = query.where(Entity.properties[f].astext == str(val))
    return await session.scalar(query)


async def _find_by_name(
    session: AsyncSession, type_id: uuid.UUID, name: str
) -> Entity | None:
    return await session.scalar(
        select(Entity).where(
            Entity.type_id == type_id,
            Entity.properties["name"].astext == name,
        )
    )


async def _find_by_title(
    session: AsyncSession, type_id: uuid.UUID, title: str
) -> Entity | None:
    return await session.scalar(
        select(Entity).where(
            Entity.type_id == type_id,
            Entity.properties["title"].astext == title,
        )
    )


_NON_IDENTITY_FIELDS = {"status", "description", "outcome_summary", "notes", "summary", "type", "industry", "role"}

async def _find_by_any_string_overlap(
    session: AsyncSession, type_id: uuid.UUID, properties: dict
) -> Entity | None:
    """Last-resort: if two or more identifying string properties match an existing entity, merge."""
    id_props = {
        k: v for k, v in properties.items()
        if isinstance(v, str) and v.strip() and k not in _NON_IDENTITY_FIELDS
    }
    if len(id_props) < 2:
        return None
    candidates = (await session.execute(select(Entity).where(Entity.type_id == type_id))).scalars().all()
    for existing in candidates:
        ep = existing.properties or {}
        matches = sum(1 for k, v in id_props.items() if ep.get(k) == v)
        if matches >= 2:
            return existing
    return None


async def _resolve_edge_type(
    session: AsyncSession, label: str, run_ctx: RunContext, existing_types: list[dict]
) -> "EdgeType | None":
    et = await session.scalar(select(EdgeType).where(EdgeType.name == label))
    if et:
        return et
    # Before creating a new type, check if an existing one is semantically equivalent
    canonical_name = await llm_edge_type_normalize(label, existing_types)
    if canonical_name:
        canonical_et = await session.scalar(select(EdgeType).where(EdgeType.name == canonical_name))
        if canonical_et:
            logger.info("Normalized edge type %r → existing %r", label, canonical_name)
            return canonical_et
    semantics = await llm_edge_type_classify(label, existing_types)
    new_et = EdgeType(
        name=label,
        is_transitive=semantics["is_transitive"],
        is_inverse_of=semantics["is_inverse_of"],
        domain=semantics["domain"],
        range_=semantics["range_"],
    )
    session.add(new_et)
    await session.flush()
    session.add(OntologyEvent(
        event_type="edge_type_created",
        actor=f"agent:{run_ctx.agent_entity_id}",
        payload={"name": label, "semantics": semantics},
    ))
    return new_et
