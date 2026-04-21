import asyncio
import json
import os
import sys
import uuid
from typing import Any

# Ensure agent-core is on the path so db, spec_factory, etc. are importable.
AGENT_CORE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "agent-core"))
sys.path.insert(0, AGENT_CORE)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(AGENT_CORE, ".env"))

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from sqlalchemy import select  # noqa: E402

from db import (  # noqa: E402
    AgentSpec as DbAgentSpec,
    Edge as DbEdge,
    EdgeType as DbEdgeType,
    Entity as DbEntity,
    Message as DbMessage,
    OntologyEvent as DbOntologyEvent,
    OntologyType as DbOntologyType,
    Run as DbRun,
    db_session,
)

app = FastAPI(title="Knowledge Worker API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"ok": True}


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------

@app.get("/agents")
async def list_agents():
    async with db_session() as session:
        specs = (await session.execute(select(DbAgentSpec))).scalars().all()
        return [
            {
                "id": str(s.id),
                "name": s.name,
                "system_prompt": s.system_prompt,
                "allowed_tools": s.allowed_tools,
                "max_turns": s.max_turns,
                "status": "active",
                "icon": "🤖",
                "entity_type_scope": [],
            }
            for s in specs
        ]


@app.get("/agents/{agent_id}/tasks")
async def list_tasks(agent_id: str):
    async with db_session() as session:
        task_type = await session.scalar(
            select(DbOntologyType).where(DbOntologyType.name == "Task")
        )
        if not task_type:
            return []

        agent_type = await session.scalar(
            select(DbOntologyType).where(DbOntologyType.name == "Agent")
        )
        agent_entity = None
        if agent_type:
            agent_entity = await session.scalar(
                select(DbEntity).where(
                    DbEntity.type_id == agent_type.id,
                    DbEntity.properties["spec_id"].astext == agent_id,
                )
            )

        query = select(DbEntity).where(DbEntity.type_id == task_type.id)
        if agent_entity:
            query = query.where(DbEntity.created_by_agent_id == agent_entity.id)

        task_rows = (await session.execute(query.order_by(DbEntity.created_at.desc()))).scalars().all()

        result = []
        for t in task_rows:
            props = t.properties or {}
            runs = (
                await session.execute(
                    select(DbRun).where(DbRun.in_service_of_task_id == t.id)
                )
            ).scalars().all()
            result.append(
                {
                    "id": str(t.id),
                    "spec_id": agent_id,
                    "title": props.get("title", "Untitled"),
                    "status": props.get("status", "pending"),
                    "session_count": len(runs),
                    "entity_count": 0,
                    "outcome_summary": props.get("outcome_summary"),
                }
            )
        return result


@app.get("/tasks/{task_id}/messages")
async def get_messages(task_id: str):
    async with db_session() as session:
        runs = (
            await session.execute(
                select(DbRun)
                .where(DbRun.in_service_of_task_id == uuid.UUID(task_id))
                .order_by(DbRun.started_at)
            )
        ).scalars().all()

        messages = []
        for run in runs:
            run_msgs = (
                await session.execute(
                    select(DbMessage)
                    .where(DbMessage.run_id == run.id)
                    .order_by(DbMessage.created_at)
                )
            ).scalars().all()
            for m in run_msgs:
                content = m.content or {}
                messages.append(
                    {
                        "id": str(m.id),
                        "role": "agent" if m.role == "assistant" else m.role,
                        "content": content.get("text", ""),
                        "tool_calls": content.get("tool_calls", []),
                        "timestamp": m.created_at.strftime("%I:%M %p"),
                    }
                )
        return messages


_NAME_FIELDS = ("name", "title", "email", "domain", "company", "subject", "label", "full_name", "display_name")

def _entity_display_name(props: dict, entity_id) -> str:
    for key in _NAME_FIELDS:
        v = props.get(key)
        if v and isinstance(v, str) and v.strip():
            return v.strip()
    return str(entity_id)[:8]


@app.get("/entities")
async def list_entities(type: str | None = None):
    async with db_session() as session:
        query = select(DbEntity, DbOntologyType).join(
            DbOntologyType, DbEntity.type_id == DbOntologyType.id
        )
        if type:
            query = query.where(DbOntologyType.name == type)
        rows = (await session.execute(query)).all()
        return [
            {
                "id": str(entity.id),
                "type": otype.name,
                "name": _entity_display_name(entity.properties or {}, entity.id),
                "properties": entity.properties or {},
                "source_refs": entity.source_refs or [],
                "created_in_run_id": str(entity.created_in_run_id) if entity.created_in_run_id else None,
            }
            for entity, otype in rows
        ]


@app.get("/edges")
async def list_edges():
    async with db_session() as session:
        rows = (
            await session.execute(
                select(DbEdge, DbEdgeType).join(DbEdgeType, DbEdge.edge_type_id == DbEdgeType.id)
            )
        ).all()
        return [
            {
                "id": str(edge.id),
                "src": str(edge.src_id),
                "dst": str(edge.dst_id),
                "type": etype.name,
                "derived": False,
            }
            for edge, etype in rows
        ]


@app.get("/runs")
async def list_runs():
    async with db_session() as session:
        runs = (
            await session.execute(
                select(DbRun, DbAgentSpec)
                .join(DbAgentSpec, DbRun.spec_id == DbAgentSpec.id)
                .order_by(DbRun.started_at.desc())
            )
        ).all()
        return [
            {
                "id": str(run.id),
                "spec_id": str(run.spec_id),
                "task_id": str(run.in_service_of_task_id) if run.in_service_of_task_id else None,
                "status": "completed" if run.status == "done" else run.status,
                "started_at": run.started_at.isoformat(),
                "ended_at": run.ended_at.isoformat() if run.ended_at else None,
                "tool_call_count": 0,
                "entity_count": 0,
            }
            for run, spec in runs
        ]


@app.get("/schema/entity-types")
async def list_entity_types():
    async with db_session() as session:
        types = (await session.execute(select(DbOntologyType))).scalars().all()
        return [
            {
                "name": t.name,
                "canonical_key": t.canonical_key,
                "description": t.description if hasattr(t, "description") else None,
            }
            for t in types
        ]


@app.get("/schema/edge-types")
async def list_edge_types():
    async with db_session() as session:
        types = (await session.execute(select(DbEdgeType))).scalars().all()
        return [
            {
                "name": t.name,
                "is_transitive": t.is_transitive,
                "is_inverse_of": t.is_inverse_of,
                "domain": t.domain,
                "range": t.range_,
            }
            for t in types
        ]


@app.get("/runs/{run_id}/events")
async def get_run_events(run_id: str):
    async with db_session() as session:
        entities_in_run = (
            await session.execute(
                select(DbEntity.id).where(
                    DbEntity.created_in_run_id == uuid.UUID(run_id)
                )
            )
        ).scalars().all()

        if not entities_in_run:
            return []

        events = (
            await session.execute(
                select(DbOntologyEvent)
                .where(DbOntologyEvent.entity_id.in_(entities_in_run))
                .order_by(DbOntologyEvent.created_at)
            )
        ).scalars().all()

        return [
            {
                "id": str(e.id),
                "event_type": e.event_type,
                "actor": e.actor,
                "run_id": run_id,
                "entity_name": (e.payload or {}).get("name"),
                "payload": e.payload or {},
                "created_at": e.created_at.isoformat(),
            }
            for e in events
        ]


# ---------------------------------------------------------------------------
# /chat SSE endpoint
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    agent_id: str
    task_id: str | None = None
    message: str


async def _make_streaming_hook(queue: asyncio.Queue):
    async def hook(hook_input, session_id, hook_context):
        tool_name = (
            hook_input.get("tool_name", "")
            if isinstance(hook_input, dict)
            else getattr(hook_input, "tool_name", "")
        )
        tool_input = (
            hook_input.get("tool_input", {})
            if isinstance(hook_input, dict)
            else getattr(hook_input, "tool_input", {})
        )
        await queue.put(("tool_call", {"tool": tool_name, "args": tool_input}))
        await queue.put(("tool_result", {"tool": tool_name}))
        return {}

    return hook


@app.post("/chat")
async def chat(body: ChatRequest):
    queue: asyncio.Queue = asyncio.Queue()

    async def run_agent():
        try:
            from claude_agent_sdk import AssistantMessage, TextBlock, ToolUseBlock, query
            from spec_factory import begin_run, build_options_from_spec, end_run, get_agent_entity_id, load_spec

            async with db_session() as session:
                spec = await load_spec(session, uuid.UUID(body.agent_id))
                agent_entity_id = await get_agent_entity_id(session, spec.id)
                run_ctx = await begin_run(session, body.message, spec, agent_entity_id)

            streaming_hook = await _make_streaming_hook(queue)

            options = build_options_from_spec(
                spec, run_ctx,
                streaming_hook=streaming_hook,
                permission_mode="bypassPermissions",
            )

            sdk_messages = []
            async for sdk_msg in query(prompt=body.message, options=options):
                sdk_messages.append(sdk_msg)
                if isinstance(sdk_msg, AssistantMessage):
                    text = " ".join(
                        b.text for b in sdk_msg.content if isinstance(b, TextBlock)
                    ).strip()
                    if text:
                        await queue.put(("message", {"role": "agent", "content": text}))

            async with db_session() as session:
                for sdk_msg in sdk_messages:
                    if isinstance(sdk_msg, AssistantMessage):
                        text = " ".join(
                            b.text for b in sdk_msg.content if isinstance(b, TextBlock)
                        )
                        tool_calls = [
                            {"id": b.id, "tool": b.name, "args": b.input}
                            for b in sdk_msg.content
                            if isinstance(b, ToolUseBlock)
                        ]
                        session.add(
                            DbMessage(
                                run_id=run_ctx.run_id,
                                role="assistant",
                                content={"text": text, "tool_calls": tool_calls},
                            )
                        )
                session.add(
                    DbMessage(
                        run_id=run_ctx.run_id,
                        role="user",
                        content={"text": body.message, "tool_calls": []},
                    )
                )
                await end_run(session, run_ctx, sdk_messages)

            await queue.put(
                ("done", {"run_id": str(run_ctx.run_id), "task_id": str(run_ctx.task_id)})
            )
        except Exception as exc:
            await queue.put(("error", {"detail": str(exc)}))
        finally:
            await queue.put(None)

    asyncio.create_task(run_agent())

    async def event_generator():
        while True:
            item = await queue.get()
            if item is None:
                break
            event_type, data = item
            yield f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Builder endpoints
# ---------------------------------------------------------------------------

class GenerateRequest(BaseModel):
    description: str


@app.post("/builder/generate")
async def builder_generate(body: GenerateRequest):
    from builder_agent import generate_spec
    return await generate_spec(body.description)


class CreateAgentRequest(BaseModel):
    name: str
    system_prompt: str
    capabilities: list[str] = []


def _spec_to_dict(spec: DbAgentSpec) -> dict:
    return {
        "id": str(spec.id),
        "name": spec.name,
        "system_prompt": spec.system_prompt,
        "allowed_tools": spec.allowed_tools,
        "max_turns": spec.max_turns,
        "status": "active",
        "icon": "🤖",
        "entity_type_scope": [],
    }


@app.post("/agents")
async def create_agent(body: CreateAgentRequest):
    from builder_agent import capabilities_to_tools
    tools = capabilities_to_tools(body.capabilities)
    async with db_session() as session:
        spec = DbAgentSpec(
            name=body.name,
            system_prompt=body.system_prompt,
            allowed_tools=tools,
            allowed_mcp_servers={},
            max_turns=30,
        )
        session.add(spec)
        await session.flush()
        return _spec_to_dict(spec)


class UpdateAgentRequest(BaseModel):
    name: str | None = None
    system_prompt: str | None = None
    capabilities: list[str] | None = None


@app.patch("/agents/{agent_id}")
async def update_agent(agent_id: str, body: UpdateAgentRequest):
    from fastapi import HTTPException
    from builder_agent import capabilities_to_tools
    async with db_session() as session:
        spec = await session.get(DbAgentSpec, uuid.UUID(agent_id))
        if not spec:
            raise HTTPException(status_code=404, detail="Agent not found")
        if body.name is not None:
            spec.name = body.name
        if body.system_prompt is not None:
            spec.system_prompt = body.system_prompt
        if body.capabilities is not None:
            spec.allowed_tools = capabilities_to_tools(body.capabilities)
        await session.flush()
        return _spec_to_dict(spec)
