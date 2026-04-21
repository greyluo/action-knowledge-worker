import asyncio
import json
import os
import sys
import uuid
from datetime import datetime
from typing import Any

# Inject worktree so we can import db, spec_factory, ontologist, etc.
WORKTREE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", ".worktrees", "agent-builder-mvp")
)
sys.path.insert(0, WORKTREE)

# Load .env from worktree before db.py is imported (db.py's own load_dotenv
# won't find it when CWD is backend/).
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(WORKTREE, ".env"))

import anthropic  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
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
    allow_origins=["http://localhost:5173"],
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
                "name": (entity.properties or {}).get(
                    "name",
                    (entity.properties or {}).get("title", str(entity.id)[:8]),
                ),
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


async def _make_streaming_hook(run_ctx: Any, queue: asyncio.Queue):
    from ontologist import make_ontologist_hook

    ontologist_hook = make_ontologist_hook(run_ctx)

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
        result = await ontologist_hook(hook_input, session_id, hook_context)
        await queue.put(("tool_result", {"tool": tool_name}))
        return result

    return hook


@app.post("/chat")
async def chat(body: ChatRequest):
    queue: asyncio.Queue = asyncio.Queue()

    async def run_agent():
        try:
            from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, HookMatcher, TextBlock, ToolUseBlock, query
            from mock_tools import demo_server
            from spec_factory import begin_run, end_run, get_agent_entity_id, load_spec

            async with db_session() as session:
                spec = await load_spec(session, uuid.UUID(body.agent_id))
                agent_entity_id = await get_agent_entity_id(session, spec.id)
                run_ctx = await begin_run(session, body.message, spec, agent_entity_id)

            streaming_hook = await _make_streaming_hook(run_ctx, queue)

            options = ClaudeAgentOptions(
                system_prompt=spec.system_prompt,
                allowed_tools=spec.allowed_tools,
                mcp_servers={"demo": demo_server},
                hooks={"PostToolUse": [HookMatcher(matcher="*", hooks=[streaming_hook])]},
                max_turns=spec.max_turns or 20,
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
# /builder/chat SSE endpoint
# ---------------------------------------------------------------------------

class BuilderMessage(BaseModel):
    role: str
    content: str


class BuilderChatRequest(BaseModel):
    message: str
    agent_id: str | None = None
    history: list[BuilderMessage] = []


BUILDER_SYSTEM = """You are an agent spec designer. Help the user define a Claude agent by asking clarifying questions one at a time about:
- What the agent should do (its goal)
- What tools it should have access to (choose from: fetch_company_data, fetch_email_thread, query_graph)
- How many turns it should run (1-30)
- A short name for the agent

Once you have enough information (at minimum: goal and at least one tool), output the spec as a JSON block in this exact format (no markdown fence, no extra text after):

AGENT_SPEC: {"name": "...", "system_prompt": "...", "allowed_tools": [...], "max_turns": 20}

Until then, ask one question at a time."""


@app.post("/builder/chat")
async def builder_chat(body: BuilderChatRequest):
    anthropic_client = anthropic.AsyncAnthropic()

    messages = [{"role": m.role, "content": m.content} for m in body.history]
    messages.append({"role": "user", "content": body.message})

    async def event_generator():
        full_response = ""
        try:
            async with anthropic_client.messages.stream(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                system=BUILDER_SYSTEM,
                messages=messages,
            ) as stream:
                async for text in stream.text_stream:
                    full_response += text
                    yield f"event: token\ndata: {json.dumps({'text': text})}\n\n"

            if "AGENT_SPEC:" in full_response:
                idx = full_response.index("AGENT_SPEC:") + len("AGENT_SPEC:")
                raw_json = full_response[idx:].strip()
                brace = raw_json.find("{")
                end = raw_json.rfind("}") + 1
                if brace != -1 and end > brace:
                    spec_dict = json.loads(raw_json[brace:end])
                    async with db_session() as session:
                        if body.agent_id:
                            existing = await session.get(DbAgentSpec, uuid.UUID(body.agent_id))
                            if existing:
                                existing.name = spec_dict.get("name", existing.name)
                                existing.system_prompt = spec_dict.get("system_prompt", existing.system_prompt)
                                existing.allowed_tools = spec_dict.get("allowed_tools", existing.allowed_tools)
                                existing.max_turns = spec_dict.get("max_turns", existing.max_turns)
                                saved = existing
                            else:
                                saved = DbAgentSpec(
                                    name=spec_dict.get("name", "New Agent"),
                                    system_prompt=spec_dict.get("system_prompt", ""),
                                    allowed_tools=spec_dict.get("allowed_tools", []),
                                    allowed_mcp_servers={},
                                    max_turns=spec_dict.get("max_turns", 20),
                                )
                                session.add(saved)
                        else:
                            saved = DbAgentSpec(
                                name=spec_dict.get("name", "New Agent"),
                                system_prompt=spec_dict.get("system_prompt", ""),
                                allowed_tools=spec_dict.get("allowed_tools", []),
                                allowed_mcp_servers={},
                                max_turns=spec_dict.get("max_turns", 20),
                            )
                            session.add(saved)
                        await session.flush()
                        saved_id = str(saved.id)

                    yield f"event: spec_saved\ndata: {json.dumps({**spec_dict, 'id': saved_id})}\n\n"

        except Exception as exc:
            yield f"event: error\ndata: {json.dumps({'detail': str(exc)})}\n\n"

        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
