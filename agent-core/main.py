"""CLI entry point for the knowledge-worker agent demo.

Usage:
    python main.py "Get information about Acme Corp"          # run default agent
    python main.py --spec library-agent "Find all books"      # run a named agent spec
    python main.py dump-graph <run_id>                        # inspect a run's graph
    python main.py dump-task <task_id>                        # inspect a task's subgraph
    python main.py test-flow                                  # end-to-end: spec → run → verify ontology
    python main.py demo-chain "Research Acme Corp"            # run the 3-agent chain
"""
import asyncio
import sys
import uuid


def _print_usage() -> None:
    print(__doc__.strip())


async def run_agent(prompt: str, spec_name: str | None = None) -> None:
    """Seed the DB, build options, run the agent, and finalize the run."""
    from db import AgentSpec, db_session
    from seed import run_seed
    from spec_factory import begin_run, build_options_from_spec, end_run, get_agent_entity_id
    from sqlalchemy import select

    async with db_session() as session:
        await run_seed(session)
        if spec_name:
            spec = await session.scalar(select(AgentSpec).where(AgentSpec.name == spec_name))
            if spec is None:
                print(
                    f"ERROR: No AgentSpec named {spec_name!r}. "
                    "Run seed_demo_topology.py to create topology agents.",
                    file=sys.stderr,
                )
                sys.exit(1)
        else:
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

    from mock_tools import _background_tasks
    while _background_tasks:
        print(f"\n[chain] waiting for {len(_background_tasks)} delegated agent(s)…")
        await asyncio.gather(*list(_background_tasks), return_exceptions=True)


_TEST_SPEC = {
    "name": "acme-researcher",
    "system_prompt": (
        "You are a research agent specialising in Acme Corp. "
        "Fetch company data and email threads about Acme Corp, then produce a "
        "structured summary covering: key people, the company profile, and any "
        "open deals or opportunities. End your final message with "
        "OUTCOME_SUMMARY: followed by a one-paragraph summary."
    ),
    "allowed_tools": [
        "mcp__demo__fetch_company_data",
        "mcp__demo__fetch_email_thread",
    ],
    "max_turns": 10,
}

_TEST_PROMPT = "Fetch information about Acme Corp and summarise what you find."


async def cmd_test_flow() -> None:
    """End-to-end test: provision spec → run agent → verify ontology populated."""
    from sqlalchemy import select
    from db import AgentSpec, Entity, OntologyType, db_session
    from seed import run_seed
    from spec_factory import begin_run, build_options_from_spec, end_run, get_agent_entity_id

    print("\n── Step 1: seed DB and provision test spec ──")
    async with db_session() as session:
        await run_seed(session)

        existing = await session.scalar(
            select(AgentSpec).where(AgentSpec.name == _TEST_SPEC["name"])
        )
        if existing:
            spec = existing
            spec.system_prompt = _TEST_SPEC["system_prompt"]
            spec.allowed_tools = _TEST_SPEC["allowed_tools"]
            spec.max_turns = _TEST_SPEC["max_turns"]
        else:
            spec = AgentSpec(
                name=_TEST_SPEC["name"],
                system_prompt=_TEST_SPEC["system_prompt"],
                allowed_tools=_TEST_SPEC["allowed_tools"],
                allowed_mcp_servers={},
                max_turns=_TEST_SPEC["max_turns"],
            )
            session.add(spec)
            await session.flush()

        agent_entity_id = await get_agent_entity_id(session, spec.id)
        ctx = await begin_run(session, _TEST_PROMPT, spec, agent_entity_id)

    print(f"  spec_id  = {spec.id}")
    print(f"  run_id   = {ctx.run_id}")
    print(f"  task_id  = {ctx.task_id}")

    print("\n── Step 2: run agent (Stop hook will batch-extract ontology) ──")
    from claude_agent_sdk import query as sdk_query
    from claude_agent_sdk.types import AssistantMessage, TextBlock, ToolUseBlock

    options = build_options_from_spec(spec, ctx, permission_mode="bypassPermissions")
    messages = []
    async for event in sdk_query(prompt=_TEST_PROMPT, options=options):
        messages.append(event)
        if isinstance(event, AssistantMessage):
            for block in event.content:
                if isinstance(block, TextBlock) and block.text:
                    print(f"  [agent] {block.text[:200]}")
                elif isinstance(block, ToolUseBlock):
                    args_preview = str(block.input)[:80]
                    print(f"  [tool]  → {block.name}({args_preview})")

    async with db_session() as session:
        await end_run(session, ctx, messages)

    print("\n── Step 3: verify ontology entities ──")
    system_types = {"Agent", "Run", "Task", "Entity"}
    async with db_session() as session:
        rows = (
            await session.execute(
                select(Entity, OntologyType).join(OntologyType, Entity.type_id == OntologyType.id)
            )
        ).all()

    by_type: dict[str, list] = {}
    for entity, otype in rows:
        by_type.setdefault(otype.name, []).append(entity)

    domain_types = {t for t in by_type if t not in system_types}

    print(f"  Total entities : {len(rows)}")
    for type_name in sorted(by_type):
        marker = "  " if type_name in system_types else "* "
        names = [
            (e.properties or {}).get("name", str(e.id)[:8])
            for e in by_type[type_name][:3]
        ]
        print(f"  {marker}{type_name} ({len(by_type[type_name])}): {', '.join(names)}")

    if domain_types:
        print(f"\n  PASS — domain entity types created by Stop hook: {domain_types}")
    else:
        print("\n  FAIL — no domain entities found; Stop hook may not have fired")
        sys.exit(1)


async def run_demo_chain(prompt: str) -> None:
    """Run the seeded research→analyst→writer chain with bypassPermissions."""
    from db import AgentSpec, db_session
    from seed import run_seed
    from seed_demo_topology import seed_demo_topology
    from spec_factory import begin_run, build_options_from_spec, end_run, get_agent_entity_id
    from sqlalchemy import select

    await seed_demo_topology()

    async with db_session() as session:
        spec = await session.scalar(select(AgentSpec).where(AgentSpec.name == "research-agent"))
        if spec is None:
            print("ERROR: research-agent spec not found. Run seed_demo_topology.py first.", file=sys.stderr)
            sys.exit(1)
        agent_entity_id = await get_agent_entity_id(session, spec.id)
        ctx = await begin_run(session, prompt, spec, agent_entity_id)

    options = build_options_from_spec(spec, ctx, permission_mode="bypassPermissions")

    from claude_agent_sdk import query as sdk_query
    from claude_agent_sdk.types import AssistantMessage, TextBlock, ToolUseBlock

    print(f"\n{'='*60}")
    print(f"[research-agent] run_id={ctx.run_id}")
    print(f"{'='*60}")

    messages = []
    async for event in sdk_query(prompt=prompt, options=options):
        messages.append(event)
        if isinstance(event, AssistantMessage):
            for block in event.content:
                if isinstance(block, TextBlock) and block.text:
                    print(f"\n[research] {block.text[:300]}")
                elif isinstance(block, ToolUseBlock):
                    args_preview = str(block.input)[:100]
                    print(f"  → {block.name}({args_preview})")

    async with db_session() as session:
        await end_run(session, ctx, messages)

    print(f"\n[research-agent] done. run_id={ctx.run_id}")

    from mock_tools import _background_tasks
    while _background_tasks:
        print(f"\n[chain] waiting for {len(_background_tasks)} delegated agent(s)…")
        results = await asyncio.gather(*list(_background_tasks), return_exceptions=True)
        for r in results:
            if isinstance(r, BaseException):
                print(f"\n[chain ERROR] delegated agent raised: {r}", flush=True)

    print("\n[chain] all agents completed. Dumping graph…\n")
    from dump import dump_graph
    await dump_graph(ctx.run_id)


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

    # Extract --spec <name> before command parsing so it works with any prompt
    spec_name: str | None = None
    if "--spec" in args:
        idx = args.index("--spec")
        if idx + 1 >= len(args):
            print("ERROR: --spec requires a name argument", file=sys.stderr)
            sys.exit(1)
        spec_name = args[idx + 1]
        args = args[:idx] + args[idx + 2:]

    if not args:
        _print_usage()
        sys.exit(0)

    if args[0] == "test-flow":
        asyncio.run(cmd_test_flow())

    elif args[0] == "dump-graph":
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

    elif args[0] == "demo-chain":
        # Run the seeded demo topology chain with bypassPermissions
        prompt = " ".join(args[1:]) if len(args) > 1 else "Research Acme Corp, then delegate to the analyst, who delegates to the writer."
        asyncio.run(run_demo_chain(prompt))

    else:
        # Treat everything as the agent prompt
        prompt = " ".join(args)
        asyncio.run(run_agent(prompt, spec_name=spec_name))


if __name__ == "__main__":
    main()
