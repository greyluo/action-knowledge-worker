# Agent Builder MVP — Changelog

Read this before making any changes. It documents every significant decision,
bug found in production, and deviation from the original design doc.

---

## Session 1 — Initial Implementation (Tasks 1–13)

Implemented the full MVP as specified in `agent_builder_design_doc_mvp.md`.

### What was built

| File | Purpose |
|---|---|
| `db.py` | SQLAlchemy async models: OntologyType, EdgeType, Entity, Edge, OntologyEvent, AgentSpec, Run, ToolCall |
| `seed.py` | Seeds base types, edge types, one AgentSpec, one Agent entity |
| `migrations/` | Alembic migrations; run with `PYTHONPATH=. alembic upgrade head` |
| `ontologist.py` | PostToolUse hook — LLM extraction → type matching → identity resolution → persist |
| `rules.py` | Inference at query time: inverse edges + transitive closure |
| `query_graph.py` | Read-path tool: SQL + optional recursive CTE + inference |
| `mock_tools.py` | Canned MCP tools: fetch_company_data, fetch_email_thread, query_graph, remember_entity |
| `spec_factory.py` | Builds ClaudeAgentOptions from AgentSpec; begin_run/end_run lifecycle |
| `dump.py` | CLI dump_graph / dump_task for inspecting runs |
| `main.py` | CLI entry: `python main.py "<prompt>"`, `dump-graph <uuid>`, `dump-task <uuid>` |
| `tests/` | 26 passing tests across ontology, runtime, and tools |

### Three mechanics

- **Write path**: PostToolUse hook → `ontologist_step` → LLM extract entities → LLM judge REUSE/NEW → identity resolution → persist to Postgres
- **Read path**: agent calls `query_graph` tool → SQL + inference → returns typed entities + derived edges
- **Continuity**: `begin_run` resolves-or-creates a Task entity; every entity gets `in_service_of` edge to the current task; fresh sessions resume via `query_graph(related_to=task_id, max_hops=2)`

---

## Session 2 — Post-Demo Fixes and Extensions

All bugs were found during live demo runs and test iteration. None were in the
original design doc.

### Bug fixes

#### 1. LLM wrapping JSON in markdown fences
**Symptom**: `ValidationError` on parse — raw LLM output was ` ```json\n{...}\n``` `.
**Fix**: `_strip_fences(raw)` in `ontologist.py` using `re.search(r"^```(?:json)?\s*(.*?)```", s, re.DOTALL)`. Both `llm_extract` and `llm_type_match` call it before `model_validate_json`.

#### 2. Duplicate edges in DB
**Symptom**: `dump-task` showed `works_at` between the same entity pair 3–4 times.
**Fix**: Check for existing edge before `session.add(Edge(...))` in `_ontologist_step_inner`. Pre-fix edges in the DB are deduplicated at display time in `dump.py`.

#### 3. `outcome_summary` contained SDK object repr
**Symptom**: After a run, `task.properties["outcome_summary"]` contained the full Python repr of an `AssistantMessage` object, not just the text.
**Fix**: `_extract_text(msg)` helper in `spec_factory.py` walks `msg.content` and joins `TextBlock.text` values. `end_run` calls this instead of `str(msg)`.

#### 4. Merged entities missing `in_service_of` stamp
**Symptom**: Cross-session continuity test failed — entities identity-resolved from a prior run were not linked to the new task.
**Root cause**: The `continue` statement in the identity resolution loop skipped `in_service_of` stamping for merged entities.
**Fix**: Extracted `_stamp_in_service_of(session, entity_id, run_ctx)` as a reusable helper with its own dedup check. Called for BOTH newly created and merged entities, before `continue`.

#### 5. Test teardown FK violation
**Symptom**: `ForeignKeyViolationError` on `ontology_types` during test cleanup — cleanup tried to delete Person/Company/Deal types still referenced by demo entities.
**Fix**: OntologyType cleanup is now conditional — only deletes types with no remaining entity references. OntologyEvent deletion is scoped by `created_at >= cleanup_after` (timestamp from before the test started) so demo-run events are not clobbered.

#### 6. LLM extracting Task/Run/Agent entities from tool output
**Symptom**: `dump-task` showed Task and Run entities in the subgraph, including a self-loop edge (`451e6861 --in_service_of--> 451e6861`). These were created because the LLM extractor saw task-like JSON in tool output and emitted `type_hint: "Task"`.
**Fix**: Two layers:
  1. `EXTRACT_SYSTEM` prompt updated — `type_hint` schema changed from `Person|Company|Deal|Task|null` to `Person|Company|Deal|null`; rule added: "Do NOT extract system/infrastructure entities".
  2. Hard filter in `_ontologist_step_inner` — candidates with `type_hint in {"Task", "Run", "Agent", "Entity"}` are skipped before `llm_type_match`.

### New features

#### 7. `remember_entity` tool — chat-driven ontology updates
**Problem**: PostToolUse hook only fires after tool calls. Information the user provides in conversation (e.g., "Alice's email changed") was silently dropped.
**Solution**: Added `remember_entity(name, type_hint, properties)` to `mock_tools.py`. The tool echoes its input back as JSON. The PostToolUse hook fires on the output, and the ontologist processes it like any tool result. The agent's system prompt instructs it to call `remember_entity` whenever the user provides entity facts.

#### 8. `run_seed` syncs AgentSpec on every run
**Problem**: Changing `SYSTEM_PROMPT` or `allowed_tools` in `seed.py` had no effect if the spec already existed in the DB.
**Fix**: `run_seed` now updates `system_prompt` and `allowed_tools` on the existing spec on every call. Since `run_seed` is called at the start of every `python main.py` invocation, changes take effect without a DB reset.

#### 9. Name-based fallback merge
**Problem**: If a Person's email changes, `_find_by_canonical` misses the existing entity (lookup key changed), creating a duplicate. The agent would then see two Alice Chens.
**Fix**: After canonical key lookup fails, `_ontologist_step_inner` falls back to `_find_by_name(session, type_id, name)` — matching `properties["name"]` within the same type. Found entity is merged rather than duplicated. Trade-off: ambiguous if two distinct entities share a name (acceptable for single-tenant use).

#### 10. `canonical_key` moved from hardcoded dict to `OntologyType` column
**Problem**: `CANONICAL_KEYS` was hardcoded for Person/Company/Deal only. Agent-created types (e.g., Meeting, Contract) had no canonical key, so identity resolution relied on name alone regardless of what made them unique.
**Solution**:
  - Added `canonical_key: Mapped[str | None]` column to `OntologyType` in `db.py`
  - Migration: `migrations/versions/b2b7c96e4b5b_add_canonical_key_to_ontology_types.py`
  - `JUDGE_SYSTEM` prompt updated — judge is asked to propose `canonical_key` (field name or comma-separated composite) as part of the `NEW` response
  - `_persist_type` stores `proposed["canonical_key"]` in the DB
  - `_get_all_types` includes `canonical_key` in returned dicts
  - `_get_canonical_key` reads from the type dict instead of the hardcoded constant; supports comma-separated composite keys
  - `run_seed` backfills `canonical_key` on existing Person/Company/Deal types that predate the column
  - `seed.py` defines `_CANONICAL_KEY_DEFAULTS = {"Person": "email", "Company": "domain", "Deal": "name,company"}`

---

## Session 3 — Explicit Relationships and UI Polish

### New features

#### 11. `remember_entity` accepts explicit relationships

**Problem**: Agents could only persist edges through the LLM-driven PostToolUse extraction path, which infers relationships from tool output text. Explicitly known relationships (e.g. "this person borrows this book") had no direct write path.
**Solution**: Added optional `relationships` list to `remember_entity(name, type_hint, properties, relationships)`. Each entry specifies `target_name`, `target_type`, `edge_type`, and `direction` (`to_target` or `from_target`). The ontologist processes these alongside the primary entity — target entities go through the same identity-resolution path, and edges are persisted immediately.
**Library-agent prompt** updated to instruct the agent to call `remember_entity` twice when lending a book: once to record the Person with a `borrows` relationship to the Book, once to update the Book's status to `borrowed`.

#### 12. Entity types polled and auto-shown in ontology view
**Problem**: New entity types created during a run were not reflected in the ontology view filter panel without a page refresh, and newly appearing types were hidden by default.
**Fix**: `getEntityTypes` added to the 3-second polling interval in `App.tsx`. `OntologyView` now runs a `useEffect` that adds any type not yet in `shownTypes` — so new types appear automatically without overriding explicit user unchecks.

---

## Current State

- **Tests**: 26 passed, 0 errors (as of Session 2)
- **Demo**: `python main.py "Get information about Acme Corp"` runs the full write + read path
- **DB**: If you have stale demo data with duplicate entities/edges, reset with the SQL below, then re-run
- **Migrations**: Two migrations applied — `001` (initial schema) and `b2b7c96e4b5b` (canonical_key column)

### DB reset (removes all demo run data, keeps seed)

```sql
DELETE FROM edges WHERE created_in_run_id IN (SELECT id FROM runs);
DELETE FROM entities WHERE created_in_run_id IN (SELECT id FROM runs);
DELETE FROM entities WHERE type_id = (SELECT id FROM ontology_types WHERE name = 'Task');
DELETE FROM ontology_types WHERE status = 'provisional';
DELETE FROM ontology_events;
DELETE FROM runs;
```

---

## Known Limitations / Deferred

- **Name collision on fallback merge**: Two distinct people named "Alice Chen" would be incorrectly merged. Needs human-in-the-loop disambiguation or a stronger secondary key.
- **`remember_entity` email-change caveat**: Canonical key lookup uses the NEW email; if the agent passes the new email for an entity whose old email is the canonical key, the fallback-by-name merge kicks in and overwrites the old email. Works correctly.
- **Real tools**: `mock_tools.py` is a placeholder. Wire real MCP servers (Gmail, Salesforce, filesystem) via `ClaudeAgentOptions(mcp_servers={...})` in `spec_factory.py`.
- **Builder agent**: Not included in MVP per design doc §1. The AgentSpec is seeded directly in `seed.py`.
- **No PostTurn hook**: Direct chat messages only update the ontology if the agent explicitly calls `remember_entity`. A future PostTurn hook could auto-extract from every user message.
