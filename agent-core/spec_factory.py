import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import AgentSpec, Entity, OntologyType, Run, Edge, EdgeType


@dataclass
class RunContext:
    run_id: uuid.UUID
    task_id: uuid.UUID | None
    spec: AgentSpec
    agent_entity_id: uuid.UUID


async def load_spec(session: AsyncSession, spec_id: uuid.UUID) -> AgentSpec:
    spec = await session.get(AgentSpec, spec_id)
    if not spec:
        raise ValueError(f"No spec with id {spec_id}")
    return spec


async def get_agent_entity_id(session: AsyncSession, spec_id: uuid.UUID) -> uuid.UUID:
    agent_type = await session.scalar(
        select(OntologyType).where(OntologyType.name == "Agent")
    )
    agent = await session.scalar(
        select(Entity).where(
            Entity.type_id == agent_type.id,
            Entity.properties["spec_id"].astext == str(spec_id),
        )
    )
    return agent.id if agent else uuid.uuid4()


async def begin_run(
    session: AsyncSession,
    prompt: str,
    spec: AgentSpec,
    agent_entity_id: uuid.UUID,
    task_id: uuid.UUID | None = None,
) -> RunContext:
    if task_id:
        task_entity = await session.get(Entity, task_id)
        if task_entity:
            task_entity.properties = {**task_entity.properties, "status": "in_progress"}
        else:
            task_id = None

    if not task_id:
        task_entity = await _maybe_resume_task(session, prompt)
        if task_entity:
            task_entity.properties = {**task_entity.properties, "status": "in_progress"}
            task_id = task_entity.id
        else:
            task_type = await session.scalar(
                select(OntologyType).where(OntologyType.name == "Task")
            )
            title = prompt[:80] if len(prompt) > 80 else prompt
            task_entity = Entity(
                type_id=task_type.id,
                properties={
                    "title": title,
                    "description": prompt,
                    "status": "in_progress",
                    "outcome_summary": None,
                },
                source_refs=[{"source": "user_prompt"}],
                created_by_agent_id=agent_entity_id,
            )
            session.add(task_entity)
            await session.flush()
            task_id = task_entity.id

    run = Run(spec_id=spec.id, in_service_of_task_id=task_id)
    session.add(run)
    await session.flush()

    in_service_edge_type = await session.scalar(
        select(EdgeType).where(EdgeType.name == "in_service_of")
    )
    run_entity = await _get_or_create_run_entity(session, run.id, spec.id, agent_entity_id)
    session.add(Edge(
        src_id=run_entity.id,
        dst_id=task_id,
        edge_type_id=in_service_edge_type.id,
        created_by_agent_id=agent_entity_id,
        created_in_run_id=run.id,
    ))

    return RunContext(run_id=run.id, task_id=task_id, spec=spec, agent_entity_id=agent_entity_id)


async def _maybe_resume_task(session: AsyncSession, prompt: str) -> Entity | None:
    resumption_keywords = ["continue", "where were we", "pick up", "resume", "where did we"]
    if not any(kw in prompt.lower() for kw in resumption_keywords):
        return None
    task_type = await session.scalar(select(OntologyType).where(OntologyType.name == "Task"))
    if not task_type:
        return None
    result = await session.scalar(
        select(Entity)
        .where(Entity.type_id == task_type.id)
        .where(Entity.properties["status"].astext == "in_progress")
        .order_by(Entity.created_at.desc())
        .limit(1)
    )
    return result


async def _get_or_create_run_entity(
    session: AsyncSession, run_id: uuid.UUID, spec_id: uuid.UUID, agent_entity_id: uuid.UUID
) -> Entity:
    run_type = await session.scalar(select(OntologyType).where(OntologyType.name == "Run"))
    existing = await session.scalar(
        select(Entity).where(Entity.properties["run_id"].astext == str(run_id))
    )
    if existing:
        return existing
    run_entity = Entity(
        type_id=run_type.id,
        properties={"run_id": str(run_id), "spec_id": str(spec_id)},
        source_refs=[],
        created_by_agent_id=agent_entity_id,
        created_in_run_id=run_id,
    )
    session.add(run_entity)
    await session.flush()
    return run_entity


def _extract_text(msg) -> str:
    """Pull plain text out of an SDK message object or fall back to str()."""
    content = getattr(msg, "content", None)
    if content and isinstance(content, list):
        parts = []
        for block in content:
            t = getattr(block, "text", None)
            if t:
                parts.append(t)
        if parts:
            return "\n".join(parts)
    return str(msg)


async def end_run(session: AsyncSession, ctx: RunContext, messages: list) -> None:
    run = await session.get(Run, ctx.run_id)
    if run:
        run.status = "done"
        run.ended_at = datetime.now(timezone.utc)

    outcome = None
    for msg in reversed(messages):
        # Extract plain text from SDK message objects or plain strings
        text = _extract_text(msg)
        if "OUTCOME_SUMMARY:" in text:
            idx = text.index("OUTCOME_SUMMARY:") + len("OUTCOME_SUMMARY:")
            outcome = text[idx:].strip()[:1000]
            break

    task = await session.get(Entity, ctx.task_id)
    if task:
        props = dict(task.properties)
        if outcome:
            props["status"] = "completed"
            props["outcome_summary"] = outcome
        else:
            props["status"] = "in_progress"
            props["outcome_summary"] = f"Run {ctx.run_id} completed; no outcome summary emitted."
        task.properties = props


import logging as _logging
_logger = _logging.getLogger(__name__)

_ONTOLOGY_TOOLS = frozenset({
    "mcp__demo__remember_entity",
    "mcp__demo__query_graph",
})

# Tool outputs from these are not external data — skip ontology extraction
_SKIP_COLLECTION = frozenset({"mcp__demo__query_graph"})


def build_options_from_spec(
    spec: AgentSpec,
    run_ctx: RunContext,
    streaming_hook=None,
    permission_mode: str | None = None,
):
    """Build ClaudeAgentOptions from a spec and run context.

    All agents get:
    - Base ontology system prompt prepended to their goal prompt
    - query_graph and remember_entity always in allowed_tools
    - PostToolUse: collects external tool outputs (skips query_graph)
    - Stop: batch-runs the ontologist over all collected outputs
    """
    from mock_tools import demo_server
    from ontologist import ontologist_step
    from seed import SYSTEM_PROMPT as _BASE_PROMPT
    from claude_agent_sdk import ClaudeAgentOptions, HookMatcher

    if spec.system_prompt and spec.system_prompt.strip():
        system_prompt = _BASE_PROMPT + "\n\n## Agent goal\n" + spec.system_prompt.strip()
    else:
        system_prompt = _BASE_PROMPT

    allowed_tools = list(_ONTOLOGY_TOOLS | set(spec.allowed_tools or []))

    accumulated: list[tuple[str, dict, Any]] = []

    async def policy_hook(hook_input, session_id, hook_context) -> dict:
        from policies import check_policies  # noqa: PLC0415

        tool_name = hook_input.get("tool_name", "") if isinstance(hook_input, dict) else getattr(hook_input, "tool_name", "")
        tool_input_val = hook_input.get("tool_input", {}) if isinstance(hook_input, dict) else getattr(hook_input, "tool_input", {})
        hook_event_name = hook_input.get("hook_event_name", "PreToolUse") if isinstance(hook_input, dict) else getattr(hook_input, "hook_event_name", "PreToolUse")

        try:
            reason = await check_policies(tool_name, tool_input_val or {}, run_ctx)
        except Exception as exc:
            _logger.exception("policy check failed for tool %s: %s", tool_name, exc)
            return {}

        if reason:
            _logger.info("Policy blocked %s: %s", tool_name, reason)
            return {
                "systemMessage": (
                    f"Action blocked by policy: {reason} "
                    "Explain this blocking reason to the requester and do not retry."
                ),
                "hookSpecificOutput": {
                    "hookEventName": hook_event_name,
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                },
            }
        return {}

    async def collect_hook(hook_input, session_id, hook_context) -> dict:
        tool_name = hook_input.get("tool_name", "") if isinstance(hook_input, dict) else getattr(hook_input, "tool_name", "")
        tool_input_val = hook_input.get("tool_input", {}) if isinstance(hook_input, dict) else getattr(hook_input, "tool_input", {})
        tool_output = hook_input.get("tool_response", None) if isinstance(hook_input, dict) else getattr(hook_input, "tool_response", None)
        if tool_name == "mcp__demo__remember_entity":
            # Persist immediately — don't batch; user-stated facts should be available
            # to query_graph within the same session
            try:
                await ontologist_step(tool_name, tool_input_val or {}, tool_output, run_ctx)
            except Exception as exc:
                _logger.exception("remember_entity persist failed: %s", exc)
        elif tool_name not in _SKIP_COLLECTION and tool_output is not None:
            accumulated.append((tool_name, tool_input_val or {}, tool_output))
        return {}

    async def stop_hook(hook_input, session_id, hook_context) -> dict:
        for tool_name, tool_input_val, tool_output in accumulated:
            try:
                await ontologist_step(tool_name, tool_input_val, tool_output, run_ctx)
            except Exception as exc:
                _logger.exception("batch ontologist failed for tool %s: %s", tool_name, exc)
        return {}

    post_tool_hooks = [collect_hook]
    if streaming_hook:
        post_tool_hooks.append(streaming_hook)

    kwargs = {}
    if permission_mode is not None:
        kwargs["permission_mode"] = permission_mode

    return ClaudeAgentOptions(
        system_prompt=system_prompt,
        allowed_tools=allowed_tools,
        mcp_servers={"demo": demo_server},
        hooks={
            "PreToolUse": [HookMatcher(matcher="*", hooks=[policy_hook])],
            "PostToolUse": [HookMatcher(matcher="*", hooks=post_tool_hooks)],
            "Stop": [HookMatcher(matcher="*", hooks=[stop_hook])],
        },
        max_turns=spec.max_turns or 20,
        **kwargs,
    )
