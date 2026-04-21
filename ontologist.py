import json
import logging
import os
import uuid
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

# Canonical keys per type name — hardcoded narrowly to avoid edge cases
CANONICAL_KEYS: dict[str, str | list[str]] = {
    "Person": "email",
    "Company": "domain",
    "Deal": ["name", "company"],
}


class CandidateEntity(BaseModel):
    name: str
    properties: dict[str, Any]
    type_hint: str | None = None


class CandidateRelationship(BaseModel):
    src_idx: int
    dst_idx: int
    label: str


class ExtractionResult(BaseModel):
    entities: list[CandidateEntity]
    relationships: list[CandidateRelationship]


class TypeMatchResult(BaseModel):
    decision: Literal["REUSE", "NEW"]
    type_id: str | None = None
    proposed: dict | None = None
    reason: str


EXTRACT_SYSTEM = """You extract named entities and relationships from tool output JSON.
Return ONLY valid JSON matching this schema — no markdown, no explanation:
{
  "entities": [
    {"name": "<display name>", "properties": {<all known props>}, "type_hint": "<Person|Company|Deal|Task|null>"}
  ],
  "relationships": [
    {"src_idx": <int index into entities>, "dst_idx": <int index into entities>, "label": "<edge type name>"}
  ]
}
Rules:
- Extract every distinct named entity: people (with email if present), companies, deals/opportunities.
- Do NOT extract generic values like dates, counts, or boolean flags as entities.
- For relationships, only include pairs where both src and dst are in your entities list.
- If no entities, return {"entities": [], "relationships": []}.
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
            return ExtractionResult.model_validate_json(raw)
        except (ValidationError, json.JSONDecodeError, IndexError) as e:
            logger.warning("llm_extract parse failure attempt %d: %s | raw=%r", attempt, e, raw)
            if attempt == 1:
                return ExtractionResult(entities=[], relationships=[])

    return ExtractionResult(entities=[], relationships=[])


JUDGE_SYSTEM = """You classify a candidate entity against an existing type system.
Return ONLY valid JSON — no markdown, no explanation:
  {"decision": "REUSE", "type_id": "<uuid>", "reason": "..."}
  OR
  {"decision": "NEW", "proposed": {"name": "...", "fields": {...}, "parent": "Entity", "description": "..."}, "reason": "..."}

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
            return TypeMatchResult.model_validate_json(raw)
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
            entity_ids = await ontologist_step(tool_name, tool_input or {}, tool_output, run_ctx)
        except Exception as e:
            logger.exception("ontologist_step failed for tool %s: %s", tool_name, e)
            return {}

        if entity_ids:
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": json.dumps({"_ontology": {"entity_ids": [str(i) for i in entity_ids]}}),
                }
            }
        return {}

    return ontologist_hook


async def ontologist_step(
    tool_name: str,
    tool_input: dict,
    tool_output: Any,
    run_ctx: RunContext,
) -> list[uuid.UUID]:
    async with db_session() as session:
        return await _ontologist_step_inner(tool_name, tool_input, tool_output, run_ctx, session)


async def _ontologist_step_inner(
    tool_name: str,
    tool_input: dict,
    tool_output: Any,
    run_ctx: RunContext,
    session: AsyncSession,
) -> list[uuid.UUID]:
    ontology_summary = await _get_ontology_summary(session)
    extraction = await llm_extract(tool_output, ontology_summary)

    if not extraction.entities:
        return []

    existing_types = await _get_all_types(session)
    resolved_ids: list[uuid.UUID] = []

    for cand in extraction.entities:
        match = await llm_type_match(cand, existing_types)

        if match.decision == "REUSE" and match.type_id:
            type_id = uuid.UUID(match.type_id)
        else:
            type_id = await _persist_type(session, match.proposed or {}, run_ctx)
            existing_types = await _get_all_types(session)

        canonical = _get_canonical_key(existing_types, type_id)
        if canonical:
            existing = await _find_by_canonical(session, type_id, canonical, cand.properties)
            if existing:
                existing.properties = {**existing.properties, **cand.properties}
                existing.source_refs = existing.source_refs + [
                    {"tool": tool_name, "input": str(tool_input)[:200]}
                ]
                resolved_ids.append(existing.id)
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

        session.add(OntologyEvent(
            event_type="entity_created",
            actor=f"agent:{run_ctx.agent_entity_id}",
            entity_id=entity.id,
            payload={"type_id": str(type_id), "name": cand.name},
        ))

        if run_ctx.task_id:
            in_service_et = await session.scalar(
                select(EdgeType).where(EdgeType.name == "in_service_of")
            )
            if in_service_et:
                session.add(Edge(
                    src_id=entity.id,
                    dst_id=run_ctx.task_id,
                    edge_type_id=in_service_et.id,
                    created_by_agent_id=run_ctx.agent_entity_id,
                    created_in_run_id=run_ctx.run_id,
                ))

    for rel in extraction.relationships:
        if rel.src_idx < len(resolved_ids) and rel.dst_idx < len(resolved_ids):
            et = await _resolve_edge_type(session, rel.label, run_ctx)
            if et:
                session.add(Edge(
                    src_id=resolved_ids[rel.src_idx],
                    dst_id=resolved_ids[rel.dst_idx],
                    edge_type_id=et,
                    created_by_agent_id=run_ctx.agent_entity_id,
                    created_in_run_id=run_ctx.run_id,
                ))

    return resolved_ids


async def _get_ontology_summary(session: AsyncSession) -> str:
    types = (await session.execute(select(OntologyType))).scalars().all()
    lines = [f"- {t.name} (id={t.id}): fields={t.fields}" for t in types]
    return "\n".join(lines) if lines else "(no types yet)"


async def _get_all_types(session: AsyncSession) -> list[dict]:
    types = (await session.execute(select(OntologyType))).scalars().all()
    return [{"id": str(t.id), "name": t.name, "fields": t.fields, "description": t.description} for t in types]


async def _persist_type(session: AsyncSession, proposed: dict, run_ctx: RunContext) -> uuid.UUID:
    name = proposed.get("name", "Unknown")
    existing = await session.scalar(select(OntologyType).where(OntologyType.name == name))
    if existing:
        return existing.id
    ot = OntologyType(
        name=name,
        parent_name=proposed.get("parent", "Entity"),
        fields=proposed.get("fields", {}),
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
    return ot.id


def _get_canonical_key(types: list[dict], type_id: uuid.UUID) -> str | list[str] | None:
    for t in types:
        if t["id"] == str(type_id):
            return CANONICAL_KEYS.get(t["name"])
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


async def _resolve_edge_type(
    session: AsyncSession, label: str, run_ctx: RunContext
) -> uuid.UUID | None:
    et = await session.scalar(select(EdgeType).where(EdgeType.name == label))
    if et:
        return et.id
    new_et = EdgeType(name=label, is_transitive=False)
    session.add(new_et)
    await session.flush()
    session.add(OntologyEvent(
        event_type="edge_type_created",
        actor=f"agent:{run_ctx.agent_entity_id}",
        payload={"name": label},
    ))
    return new_et.id
