# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Implementation Status

The MVP is implemented in `.worktrees/agent-builder-mvp/`. Before touching that
code, read `.worktrees/agent-builder-mvp/CHANGELOG.md` — it documents every
post-spec decision and production bug fix. The worktree has its own `CLAUDE.md`
with up-to-date guidance that supersedes this file for anything inside it.

## Project Overview

A knowledge-work agent platform built on the Claude Agent SDK. An execution engine loads agent specs from Postgres, runs agents with mock tools, and maintains a generative ontology via a `PostToolUse` hook. The core claim to prove: agents both *write to* and *read from* a typed entity graph, and can resume prior work across sessions via `Task` entities.

See `agent_builder_design_doc_mvp.md` for the full spec. §1 (in-scope vs stubbed) is authoritative — do not add features not listed there.

## Development Commands

```bash
# Start Postgres
docker compose up -d

# Run all tests
pytest

# Run tests in a specific area
pytest tests/test_ontology/
pytest tests/test_runtime/
pytest tests/test_tools/

# Run a single test
pytest tests/test_ontology/test_identity_resolution.py::test_merge_by_email

# Run migrations
alembic upgrade head

# Seed the database (types, edges, one spec, one Agent entity)
python seed.py

# Run the demo agent
python main.py "Get information about Acme Corp"

# Dump the ontology graph for a run
python main.py dump-graph <run_id>

# Dump task subgraph across sessions
python main.py dump-task <task_id>
```

## Architecture

```
Spec (agent_specs row)
  └─► Engine (claude-agent-sdk)
        ├─ WRITE PATH: PostToolUse hook → ontologist → Postgres graph
        └─ READ PATH:  agent calls query_graph tool → Postgres graph → agent's next decision
```

**Three mechanics, one database:**
- **Write path** — after every tool call, `ontologist.py` extracts candidate entities via LLM, matches them to existing ontology types (LLM-as-judge: REUSE vs NEW), resolves identity by canonical key, and persists with provenance stamps (`created_by_agent_id`, `created_in_run_id`).
- **Read path** — the agent calls the `query_graph` tool to retrieve typed entities and derived edges (inverse, transitive) before deciding. Derived edges are marked `derived: true`.
- **Continuity** — every run resolves-or-creates a `Task` entity. Every entity the ontologist creates is stamped `in_service_of` the current task. Fresh sessions resume by querying the task's subgraph.

## Planned Module Layout

```
/sprint_demo
  main.py           # CLI entry: run agent, dump-graph, dump-task
  spec_factory.py   # build_options_from_spec(spec_id) → ClaudeAgentOptions
  ontologist.py     # llm_extract, llm_type_match, identity resolution, persist
  rules.py          # inference: inverse edges, transitive closure (~100 LOC)
  mock_tools.py     # canned JSON for fetch_company_data, fetch_email_thread
  db.py             # SQLAlchemy models + async session
  dump.py           # dump_graph / dump_task CLI output
  seed.py           # seed types, edge types, one spec, one Agent entity
  migrations/       # Alembic migrations
```

## Key Implementation Constraints

**Stack:** Python 3.11+, `claude-agent-sdk` (latest), `sqlalchemy` + `asyncpg`, `pydantic` v2, `alembic`, `anthropic` (for extraction and judge calls — separate from the SDK's inner LLM).

**Before writing any SDK hook code:** read the current agent SDK docs at `https://platform.claude.com/docs/en/agent-sdk/` — hook signatures may have moved.

**LLM extraction:** use Anthropic's JSON mode or strict Pydantic parsing; retry once on parse failure; log raw LLM output on failure. Inconsistent candidate shapes are the most common bug.

**Identity resolution:** hardcode canonical keys narrowly (`{"Person": "email", "Company": "domain", "Deal": "name+company"}`). Don't try to be clever — edge cases eat the sprint.

**Mock tool canned JSON** must deliberately overlap: the same Person entity appears in both `fetch_company_data` and `fetch_email_thread` responses. Without overlap, identity resolution has nothing to demonstrate.

**`query_graph` implementation:** standard SQL with optional recursive CTE for `max_hops > 1`. Apply inference rules from `rules.py` when `apply_inference=True`; mark inferred edges `derived: true` in the response.

## Seed Ontology

Four entity types: `Entity`, `Agent`, `Run`, `Task`. Six edge types: `related_to`, `created_by`, `executed_by`, `in_service_of`, `part_of` (transitive), `produced`. Inverse pairs to seed: `manages` ↔ `reports_to`, `owns` ↔ `owned_by`.

`Task.status` ∈ `{"pending", "in_progress", "blocked", "completed", "abandoned"}`.

## Database Schema Tables

`agent_specs`, `runs`, `messages`, `tool_calls`, `ontology_types`, `edge_types`, `entities`, `edges`, `ontology_events`. Skip `checkpoints` and embedding columns for the MVP.
