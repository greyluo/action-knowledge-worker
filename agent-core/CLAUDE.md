# CLAUDE.md — agent-builder-mvp worktree

**Before making any change to this codebase, read `CHANGELOG.md` in full.**
It documents every bug found in production, every design decision that deviated
from the spec, and the current known limitations. Many things that look like they
should work differently were deliberately chosen — the changelog explains why.

## Quick orientation

This is the implementation directory for the agent-builder MVP. The root repo
`CLAUDE.md` has the original spec and architecture overview. This file has
worktree-specific guidance that supersedes it where they conflict.

## Running things

```bash
# Migrations first (always)
PYTHONPATH=. alembic upgrade head

# Run all tests
python -m pytest

# Run the demo
python main.py "Get information about Acme Corp"

# Inspect a run or task
python main.py dump-graph <run_id>
python main.py dump-task <task_id>
```

## What's changed from the original spec

1. `canonical_key` is now a DB column on `OntologyType`, not a hardcoded dict
2. `run_seed` syncs AgentSpec system_prompt and allowed_tools on every run
3. Identity resolution has a name-based fallback after canonical key lookup
4. `remember_entity` tool exists for chat-driven ontology updates
5. System types (Task, Run, Agent, Entity) are filtered from LLM extraction

All details and reasoning are in `CHANGELOG.md`.

## Before adding any feature

Check `agent_builder_design_doc_mvp.md` §1 (in-scope vs stubbed). The design
doc is still authoritative for scope — don't add features not listed there
without explicit user instruction.
