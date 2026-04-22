"""Policy engine: declarative graph-based pre-action constraints.

Before a destructive tool executes, the PreToolUse hook calls check_policies().
If a policy matches the tool and finds a blocking graph condition, the hook
returns permissionDecision="deny" with the reason, and the agent surfaces it.

Flow:
  agent calls terminate_employee(employee_name="Alex")
    → PreToolUse hook fires
    → check_policies("mcp__demo__terminate_employee", {"employee_name": "Alex"}, run_ctx)
    → looks up Person("Alex") in graph
    → finds Alex has assigned_to → Project{status="pending"}
    → returns "Alex is assigned to 1 active project(s): "Mobile App Redesign""
    → hook returns deny + systemMessage
    → agent explains why request is rejected
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select

from db import Edge, EdgeType, Entity, OntologyType, PolicyRule, db_session

logger = logging.getLogger(__name__)


@dataclass
class GraphCondition:
    """Block the action if subject entity has (or lacks) a matching edge.

    invert=False (default): block when a matching edge IS found (e.g. "don't fire Alex
    while he's on an active project").
    invert=True: block when no matching edge is found (e.g. "deny access unless the
    calling agent has a 'handles' edge to the requested resource type").
    """
    edge_type: str | list[str]  # single name or list of equivalent edge types (OR semantics)
    target_type: str | None = None
    blocking_target_states: dict[str, list[Any]] = field(default_factory=dict)  # empty = any target
    message_template: str = "{subject} has active {edge_type} relationship(s)"
    invert: bool = False


@dataclass
class ActionPolicy:
    """Maps a tool name pattern to blocking graph conditions.

    subject_source="tool_input" (default): the subject entity is looked up by the value
    of tool_input[subject_key] (original behaviour).
    subject_source="actor": the subject is the agent making the call (run_ctx.agent_entity_id).
    subject_key and subject_type are ignored when subject_source="actor".
    """
    tool_pattern: str
    subject_key: str
    subject_type: str
    blocking_conditions: list[GraphCondition] = field(default_factory=list)
    subject_source: str = "tool_input"
    tool_input_filter: dict[str, Any] | None = None


def _row_to_policy(row: PolicyRule) -> ActionPolicy:
    conditions = [
        GraphCondition(
            edge_type=c["edge_type"],  # str or list[str] — both handled by _check_condition
            target_type=c.get("target_type"),
            blocking_target_states=c.get("blocking_target_states", {}),
            message_template=c.get("message_template", "{subject} has active {edge_type} relationship(s)"),
            invert=bool(c.get("invert", False)),
        )
        for c in (row.blocking_conditions or [])
    ]
    return ActionPolicy(
        tool_pattern=row.tool_pattern,
        subject_key=row.subject_key,
        subject_type=row.subject_type,
        blocking_conditions=conditions,
        subject_source=row.subject_source or "tool_input",
        tool_input_filter=row.tool_input_filter or None,
    )


async def check_policies(
    tool_name: str,
    tool_input: dict[str, Any],
    run_ctx,
) -> str | None:
    """Return a blocking reason if any policy applies, else None.

    Raises on infrastructure failure — callers must treat exceptions as deny.
    """
    async with db_session() as session:
        rows = (
            await session.execute(
                select(PolicyRule).where(PolicyRule.enabled == True)  # noqa: E712
            )
        ).scalars().all()

        for row in rows:
            if not re.search(row.tool_pattern, tool_name, re.IGNORECASE):
                continue

            policy = _row_to_policy(row)

            if policy.tool_input_filter and not all(
                str(tool_input.get(k, "")).lower() == str(v).lower()
                for k, v in policy.tool_input_filter.items()
            ):
                continue

            if policy.subject_source == "actor":
                subject = await session.get(Entity, run_ctx.agent_entity_id)
            else:
                subject_value = tool_input.get(row.subject_key)
                if not subject_value:
                    continue
                subject = await _find_entity(session, policy.subject_type, str(subject_value))
            if not subject:
                continue

            for cond in policy.blocking_conditions:
                reason = await _check_condition(session, subject, cond)
                if reason:
                    return reason

    return None


async def _find_entity(session, type_name: str, name_value: str) -> "Entity | None":
    ot = await session.scalar(select(OntologyType).where(OntologyType.name == type_name))
    if not ot:
        return None
    entity = await session.scalar(
        select(Entity).where(
            Entity.type_id == ot.id,
            func.lower(Entity.properties["name"].astext) == name_value.lower(),
        )
    )
    return entity


async def _check_condition(session, subject: "Entity", cond: GraphCondition) -> str | None:
    explicit_names = cond.edge_type if isinstance(cond.edge_type, list) else [cond.edge_type]

    # Expand each named edge type to include its DB-defined synonyms
    expanded: list[str] = []
    for et_name in explicit_names:
        if et_name not in expanded:
            expanded.append(et_name)
        et = await session.scalar(select(EdgeType).where(EdgeType.name == et_name))
        if et and et.synonyms:
            for syn in et.synonyms:
                if syn not in expanded:
                    expanded.append(syn)

    edge_type_label = " / ".join(expanded)

    edges = []
    for et_name in expanded:
        et = await session.scalar(select(EdgeType).where(EdgeType.name == et_name))
        if not et:
            continue
        batch = (
            await session.execute(
                select(Edge).where(
                    Edge.src_id == subject.id,
                    Edge.edge_type_id == et.id,
                )
            )
        ).scalars().all()
        edges.extend(batch)

    blocking_targets: list[str] = []
    for edge in edges:
        target = await session.get(Entity, edge.dst_id)
        if not target:
            continue

        if cond.target_type:
            target_ot = await session.get(OntologyType, target.type_id)
            if not target_ot or target_ot.name != cond.target_type:
                continue

        props = target.properties or {}
        is_blocked = True
        for field_name, allowed_values in cond.blocking_target_states.items():
            if props.get(field_name) not in allowed_values:
                is_blocked = False
                break

        if is_blocked:
            label = props.get("name") or props.get("title") or str(target.id)[:8]
            blocking_targets.append(label)

    subject_name = (subject.properties or {}).get("name", str(subject.id)[:8])

    def _render(targets: list[str]) -> str:
        return (
            cond.message_template
            .replace("{subject}", subject_name)
            .replace("{edge_type}", edge_type_label)
            .replace("{count}", str(len(targets)))
            .replace("{targets}", ", ".join(f'"{t}"' for t in targets))
        )

    if cond.invert:
        # Block when the edge is ABSENT (permission-check mode)
        return None if blocking_targets else _render([])
    else:
        # Block when the edge IS present (harm-prevention mode)
        return _render(blocking_targets) if blocking_targets else None

