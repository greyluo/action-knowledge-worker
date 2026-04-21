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

    # Verify options object has expected attributes
    assert options is not None
    assert options.system_prompt == spec.system_prompt
    # Check PostToolUse hook is wired (exact attribute depends on SDK version)
    hooks = getattr(options, 'hooks', None) or getattr(options, 'post_tool_use_hooks', None)
    assert hooks is not None, "No hooks found on options object"
