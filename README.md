# Action Knowledge Worker

A knowledge-work agent platform built on the [Claude Agent SDK](https://platform.claude.com/docs/en/agent-sdk/). Agents process tasks using mock CRM tools, and every tool call automatically populates a typed entity graph in Postgres. Agents read from that same graph before deciding — closing a write/read loop that persists knowledge across sessions.

## What's inside

```
agent-core/   Python engine: agent runtime, ontologist, graph DB, policies, CLI
backend/      FastAPI server exposing REST + SSE endpoints
frontend/     React app: workspace chat, 3D ontology view, policy builder
```

### Core mechanics

| Path | How it works |
|------|-------------|
| **Write** | `PostToolUse` hook → `ontologist.py` extracts entities via LLM, matches them to ontology types, resolves identity by canonical key, and persists to Postgres with provenance stamps |
| **Read** | Agent calls `query_graph` tool → retrieves typed entities and derived (inferred) edges before making decisions |
| **Continuity** | Every run resolves-or-creates a `Task` entity. Fresh sessions resume by querying the task's subgraph |
| **Delegation** | `delegate_task` spawns a child agent, wires a `part_of` task edge, and forwards context entity IDs |
| **Policies** | Per-agent rules block or allow tools based on entity type, tool input shape, or source agent |

### Mock tools (canned CRM data)

- `fetch_company_data` — employees, contacts, and open deals for Acme Corp / Globex Corp / TechStartup
- `fetch_email_thread` — email threads referencing those deals and people
- `terminate_employee` — destructive action (used in policy demos)
- `remember_entity` — chat-driven ontology update
- `query_graph` — read back from the entity graph

The same person (Alice Chen, alice@acme.com) appears in multiple tools' responses on purpose — identity resolution has to merge them.

## Prerequisites

- Python 3.11+
- Node.js 20+
- Docker (for Postgres)
- An `ANTHROPIC_API_KEY`

## Setup

### 1. Start Postgres

```bash
cd agent-core
docker compose up -d
```

### 2. Python environment

```bash
cd agent-core
pip install -e ".[dev]"
```

Create `agent-core/.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/sprint_demo
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/sprint_demo_test
```

### 3. Run migrations and seed

```bash
cd agent-core
PYTHONPATH=. alembic upgrade head
python seed.py
```

To also seed the three-agent demo chain (Research → Analyst → Writer):

```bash
python seed_demo_topology.py
```

## Running the CLI demo

```bash
cd agent-core

# Run the default agent
python main.py "Get information about Acme Corp"

# Run a named agent spec
python main.py --spec library-agent "Find all books"

# Run the 3-agent delegation chain
python main.py demo-chain "Research Acme Corp"

# Inspect a run's entity graph
python main.py dump-graph <run_id>

# Inspect a task's subgraph across sessions
python main.py dump-task <task_id>
```

## Running the web UI

**Backend** (FastAPI + SSE):

```bash
cd backend
pip install -r requirements.txt
uvicorn api:app --reload --port 8000
```

**Frontend** (React + Vite):

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). Three tabs:

- **Workspace** — select an agent, start a task, watch tool calls stream live
- **Ontology** — 3D force-graph of all entities and edges built up across runs
- **Policies** — create and manage per-agent policy rules

## Running tests

```bash
cd agent-core
python -m pytest
```

## Project structure

```
agent-core/
  main.py              CLI entry point
  spec_factory.py      Build ClaudeAgentOptions from an AgentSpec row
  ontologist.py        LLM extraction, type matching, identity resolution, persist
  query_graph.py       SQL + recursive CTE graph queries with inference
  rules.py             Inference: inverse edges, transitive closure
  mock_tools.py        MCP server with canned CRM data + delegate_task
  policies.py          Policy enforcement (check_policies)
  policy_builder.py    LLM-assisted policy generation
  db.py                SQLAlchemy models + async session
  seed.py              Seed ontology types, edge types, default agent spec
  seed_demo_topology.py  Seed 3-agent Research→Analyst→Writer chain
  migrations/          Alembic migrations
  tests/               pytest suite (ontology, runtime, tools)
backend/
  api.py               FastAPI app, REST + SSE endpoints
frontend/
  src/components/      BuilderPanel, SpacePanel, OntologyView, PoliciesPanel
```
