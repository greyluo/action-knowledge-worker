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

from sqlalchemy import select

from db import Edge, EdgeType, Entity, OntologyType, PolicyRule, db_session

logger = logging.getLogger(__name__)


@dataclass
class GraphCondition:
    """Block the action if subject entity has a matching edge to a target in a blocking state."""
    edge_type: str
    target_type: str | None = None
    blocking_target_states: dict[str, list[Any]] = field(default_factory=dict)
    message_template: str = "{subject} has active {edge_type} relationship(s)"


@dataclass
class ActionPolicy:
    """Maps a tool name pattern to blocking graph conditions."""
    tool_pattern: str
    subject_key: str        # key in tool_input that names the subject entity
    subject_type: str       # ontology type to search
    blocking_conditions: list[GraphCondition] = field(default_factory=list)


def _row_to_policy(row: PolicyRule) -> ActionPolicy:
    conditions = [
        GraphCondition(
            edge_type=c["edge_type"],
            target_type=c.get("target_type"),
            blocking_target_states=c.get("blocking_target_states", {}),
            message_template=c.get("message_template", "{subject} has active {edge_type} relationship(s)"),
        )
        for c in (row.blocking_conditions or [])
    ]
    return ActionPolicy(
        tool_pattern=row.tool_pattern,
        subject_key=row.subject_key,
        subject_type=row.subject_type,
        blocking_conditions=conditions,
    )


async def check_policies(
    tool_name: str,
    tool_input: dict[str, Any],
    run_ctx,
) -> str | None:
    """Return a blocking reason if any policy applies, else None."""
    try:
        async with db_session() as session:
            rows = (
                await session.execute(
                    select(PolicyRule).where(PolicyRule.enabled == True)  # noqa: E712
                )
            ).scalars().all()

            for row in rows:
                if not re.search(row.tool_pattern, tool_name, re.IGNORECASE):
                    continue

                subject_value = tool_input.get(row.subject_key)
                if not subject_value:
                    continue

                policy = _row_to_policy(row)
                subject = await _find_entity(session, policy.subject_type, str(subject_value))
                if not subject:
                    continue

                for cond in policy.blocking_conditions:
                    try:
                        reason = await _check_condition(session, subject, cond)
                    except Exception as exc:
                        logger.exception("policy graph query failed for %s: %s", tool_name, exc)
                        continue
                    if reason:
                        return reason

    except Exception as exc:
        logger.exception("policy check failed for tool %s: %s", tool_name, exc)

    return None


async def _find_entity(session, type_name: str, name_value: str) -> "Entity | None":
    ot = await session.scalar(select(OntologyType).where(OntologyType.name == type_name))
    if not ot:
        return None
    entity = await session.scalar(
        select(Entity).where(
            Entity.type_id == ot.id,
            Entity.properties["name"].astext == name_value,
        )
    )
    return entity


async def _check_condition(session, subject: "Entity", cond: GraphCondition) -> str | None:
    et = await session.scalar(select(EdgeType).where(EdgeType.name == cond.edge_type))
    if not et:
        return None

    edges = (
        await session.execute(
            select(Edge).where(
                Edge.src_id == subject.id,
                Edge.edge_type_id == et.id,
            )
        )
    ).scalars().all()

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

    if not blocking_targets:
        return None

    subject_name = (subject.properties or {}).get("name", str(subject.id)[:8])
    return (
        cond.message_template
        .replace("{subject}", subject_name)
        .replace("{edge_type}", cond.edge_type)
        .replace("{count}", str(len(blocking_targets)))
        .replace("{targets}", ", ".join(f'"{t}"' for t in blocking_targets))
    )
