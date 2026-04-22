import pytest
from db import AgentSpec
import uuid


async def test_build_options_returns_claude_agent_options(session):
    from seed import run_seed
    await run_seed(session)

    from sqlalchemy import select
    spec = await session.scalar(select(AgentSpec).where(AgentSpec.name == "demo-agent"))

    from spec_factory import RunContext, build_options_from_spec
    ctx = RunContext(run_id=uuid.uuid4(), task_id=uuid.uuid4(), spec=spec, agent_entity_id=uuid.uuid4())

    options = build_options_from_spec(spec, ctx)

    from seed import SYSTEM_PROMPT as BASE_PROMPT

    assert options is not None
    # Base ontology prompt is always injected regardless of spec content
    assert options.system_prompt.startswith(BASE_PROMPT)
    # Ontology tools are always present
    assert "mcp__demo__query_graph" in options.allowed_tools
    assert "mcp__demo__remember_entity" in options.allowed_tools
    # PostToolUse hook is wired
    hooks = getattr(options, 'hooks', None) or getattr(options, 'post_tool_use_hooks', None)
    assert hooks is not None, "No hooks found on options object"
