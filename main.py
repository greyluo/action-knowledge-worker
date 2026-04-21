"""CLI entry point for the knowledge-worker agent demo.

Usage:
    python main.py "Get information about Acme Corp"   # run the agent
    python main.py dump-graph <run_id>                 # inspect a run's graph
    python main.py dump-task <task_id>                 # inspect a task's subgraph
"""
import asyncio
import sys
import uuid


def _print_usage() -> None:
    print(__doc__.strip())


async def run_agent(prompt: str) -> None:
    """Seed the DB, build options, run the agent, and finalize the run."""
    from db import AgentSpec, db_session
    from seed import run_seed
    from spec_factory import begin_run, build_options_from_spec, end_run, get_agent_entity_id
    from sqlalchemy import select

    async with db_session() as session:
        await run_seed(session)
        spec = await session.scalar(select(AgentSpec))
        if spec is None:
            print("ERROR: No AgentSpec found after seeding.", file=sys.stderr)
            sys.exit(1)
        agent_entity_id = await get_agent_entity_id(session, spec.id)
        ctx = await begin_run(session, prompt, spec, agent_entity_id)

    options = build_options_from_spec(spec, ctx)

    from claude_agent_sdk import query as sdk_query

    from claude_agent_sdk.types import AssistantMessage, TextBlock, ToolUseBlock

    messages = []
    async for event in sdk_query(prompt=prompt, options=options):
        messages.append(event)
        if isinstance(event, AssistantMessage):
            for block in event.content:
                if isinstance(block, TextBlock) and block.text:
                    print(f"\n[agent] {block.text}")
                elif isinstance(block, ToolUseBlock):
                    print(f"  → {block.name}({block.input})")

    async with db_session() as session:
        await end_run(session, ctx, messages)

    print(f"Run complete. run_id={ctx.run_id}")


async def cmd_dump_graph(run_id_str: str) -> None:
    try:
        run_id = uuid.UUID(run_id_str)
    except ValueError:
        print(f"ERROR: Invalid UUID: {run_id_str!r}", file=sys.stderr)
        sys.exit(1)

    from dump import dump_graph
    await dump_graph(run_id)


async def cmd_dump_task(task_id_str: str) -> None:
    try:
        task_id = uuid.UUID(task_id_str)
    except ValueError:
        print(f"ERROR: Invalid UUID: {task_id_str!r}", file=sys.stderr)
        sys.exit(1)

    from dump import dump_task
    await dump_task(task_id)


def main() -> None:
    args = sys.argv[1:]

    if not args:
        _print_usage()
        sys.exit(0)

    if args[0] == "dump-graph":
        if len(args) < 2:
            print("Usage: python main.py dump-graph <run_id>", file=sys.stderr)
            sys.exit(1)
        asyncio.run(cmd_dump_graph(args[1]))

    elif args[0] == "dump-task":
        if len(args) < 2:
            print("Usage: python main.py dump-task <task_id>", file=sys.stderr)
            sys.exit(1)
        asyncio.run(cmd_dump_task(args[1]))

    elif args[0] in ("--help", "-h", "help"):
        _print_usage()
        sys.exit(0)

    else:
        # Treat everything as the agent prompt
        prompt = " ".join(args)
        asyncio.run(run_agent(prompt))


if __name__ == "__main__":
    main()
