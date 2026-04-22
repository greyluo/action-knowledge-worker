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

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from sqlalchemy import delete as sql_delete, select, update as sql_update  # noqa: E402

from db import (  # noqa: E402
    AgentSpec as DbAgentSpec,
    Delegation as DbDelegation,
    Edge as DbEdge,
    EdgeType as DbEdgeType,
    Entity as DbEntity,
    Message as DbMessage,
    OntologyEvent as DbOntologyEvent,
    OntologyType as DbOntologyType,
    PolicyRule as DbPolicyRule,
    Run as DbRun,
    ToolCall as DbToolCall,
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
        # Find all task IDs via runs — runs always carry the spec_id directly,
        # so this works even if the Agent ontology entity is missing.
        run_rows = (
            await session.execute(
                select(DbRun)
                .where(
                    DbRun.spec_id == uuid.UUID(agent_id),
                    DbRun.in_service_of_task_id.isnot(None),
                )
            )
        ).scalars().all()

        task_ids = list({r.in_service_of_task_id for r in run_rows})
        if not task_ids:
            return []

        # Group run counts by task
        run_count: dict[uuid.UUID, int] = {}
        for r in run_rows:
            run_count[r.in_service_of_task_id] = run_count.get(r.in_service_of_task_id, 0) + 1

        task_entities = (
            await session.execute(
                select(DbEntity)
                .where(DbEntity.id.in_(task_ids))
                .order_by(DbEntity.created_at.desc())
            )
        ).scalars().all()

        return [
            {
                "id": str(t.id),
                "spec_id": agent_id,
                "title": (t.properties or {}).get("title", "Untitled"),
                "status": (t.properties or {}).get("status", "pending"),
                "session_count": run_count.get(t.id, 0),
                "entity_count": 0,
                "outcome_summary": (t.properties or {}).get("outcome_summary"),
            }
            for t in task_entities
        ]


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


@app.delete("/tasks/{task_id}", status_code=204)
async def delete_task(task_id: str):
    async with db_session() as session:
        tid = uuid.UUID(task_id)
        runs = (await session.execute(select(DbRun).where(DbRun.in_service_of_task_id == tid))).scalars().all()
        run_ids = [r.id for r in runs]
        if run_ids:
            await session.execute(sql_update(DbEntity).where(DbEntity.created_in_run_id.in_(run_ids)).values(created_in_run_id=None))
            await session.execute(sql_update(DbEdge).where(DbEdge.created_in_run_id.in_(run_ids)).values(created_in_run_id=None))
            await session.execute(sql_delete(DbToolCall).where(DbToolCall.run_id.in_(run_ids)))
            await session.execute(sql_delete(DbMessage).where(DbMessage.run_id.in_(run_ids)))
        for run in runs:
            await session.delete(run)
        await session.flush()
        # Clear delegation references before deleting the task entity
        await session.execute(sql_update(DbDelegation).where(DbDelegation.task_entity_id == tid).values(task_entity_id=None))
        await session.execute(sql_delete(DbEdge).where(DbEdge.src_id == tid))
        await session.execute(sql_delete(DbEdge).where(DbEdge.dst_id == tid))
        task = await session.get(DbEntity, tid)
        if task:
            await session.delete(task)


_NAME_FIELDS = ("name", "full_name", "display_name", "title", "company", "subject", "label", "email")

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


@app.get("/delegations")
async def list_delegations(run_id: str | None = None):
    async with db_session() as session:
        query = select(DbDelegation)
        if run_id:
            query = query.where(DbDelegation.parent_run_id == uuid.UUID(run_id))
        rows = (await session.execute(query.order_by(DbDelegation.created_at))).scalars().all()
        return [
            {
                "id": str(d.id),
                "parent_run_id": str(d.parent_run_id),
                "child_run_id": str(d.child_run_id) if d.child_run_id else None,
                "task_entity_id": str(d.task_entity_id) if d.task_entity_id else None,
                "to_agent_spec_id": str(d.to_agent_spec_id),
                "status": d.status,
                "context_ids": d.context_ids or [],
                "created_at": d.created_at.isoformat(),
                "completed_at": d.completed_at.isoformat() if d.completed_at else None,
            }
            for d in rows
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
                "fields": t.fields or {},
            }
            for t in types
        ]


@app.get("/tools")
async def list_tools():
    """Return all tools known to the system with their string-typed parameter names."""
    from mock_tools import (  # noqa: PLC0415
        fetch_company_data, fetch_email_thread, terminate_employee,
        remember_entity, query_graph_tool,
    )
    demo_tools = [fetch_company_data, fetch_email_thread, terminate_employee, remember_entity, query_graph_tool]
    tool_map = {
        f"mcp__demo__{t.name}": [k for k, v in t.input_schema.items() if v is str]
        for t in demo_tools
    }

    async with db_session() as session:
        specs = (await session.execute(select(DbAgentSpec))).scalars().all()
        result = []
        seen: set[str] = set()
        for spec in specs:
            for tool_name in (spec.allowed_tools or []):
                if tool_name not in seen:
                    seen.add(tool_name)
                    params = tool_map.get(tool_name, [])
                    # Only include tools that have known parameters — skip bare
                    # capability tools (Read, Write, Bash, etc.) which have no
                    # relevant entity identifier parameter.
                    if params or tool_name in tool_map:
                        result.append({"name": tool_name, "parameters": params})
    return result


class CreateEntityTypeRequest(BaseModel):
    name: str
    canonical_key: str | None = None
    description: str | None = None


@app.post("/schema/entity-types", status_code=201)
async def create_entity_type(body: CreateEntityTypeRequest):
    async with db_session() as session:
        existing = await session.scalar(select(DbOntologyType).where(DbOntologyType.name == body.name))
        if existing:
            raise HTTPException(status_code=409, detail=f"Entity type '{body.name}' already exists")
        otype = DbOntologyType(name=body.name, canonical_key=body.canonical_key or None, description=body.description or None)
        session.add(otype)
        await session.flush()
        return {"name": otype.name, "canonical_key": otype.canonical_key, "description": otype.description}


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
                "synonyms": t.synonyms or [],
            }
            for t in types
        ]


# ---------------------------------------------------------------------------
# Entity / Edge CRUD
# ---------------------------------------------------------------------------

def _entity_row(entity: DbEntity, type_name: str) -> dict:
    return {
        "id": str(entity.id),
        "type": type_name,
        "name": _entity_display_name(entity.properties or {}, entity.id),
        "properties": entity.properties or {},
        "source_refs": entity.source_refs or [],
        "created_in_run_id": str(entity.created_in_run_id) if entity.created_in_run_id else None,
    }


class CreateEntityRequest(BaseModel):
    type_name: str
    properties: dict = {}


@app.post("/entities", status_code=201)
async def create_entity(body: CreateEntityRequest):
    async with db_session() as session:
        otype = await session.scalar(select(DbOntologyType).where(DbOntologyType.name == body.type_name))
        if not otype:
            raise HTTPException(status_code=404, detail=f"Entity type {body.type_name!r} not found")
        entity = DbEntity(type_id=otype.id, properties=body.properties, source_refs=[{"manual": True}])
        session.add(entity)
        await session.flush()
        return _entity_row(entity, otype.name)


class UpdateEntityRequest(BaseModel):
    properties: dict


@app.patch("/entities/{entity_id}")
async def update_entity(entity_id: str, body: UpdateEntityRequest):
    async with db_session() as session:
        entity = await session.get(DbEntity, uuid.UUID(entity_id))
        if not entity:
            raise HTTPException(status_code=404, detail="Entity not found")
        entity.properties = body.properties
        await session.flush()
        otype = await session.get(DbOntologyType, entity.type_id)
        return _entity_row(entity, otype.name if otype else "Unknown")


@app.delete("/entities/{entity_id}", status_code=204)
async def delete_entity(entity_id: str):
    async with db_session() as session:
        eid = uuid.UUID(entity_id)
        entity = await session.get(DbEntity, eid)
        if not entity:
            raise HTTPException(status_code=404, detail="Entity not found")
        await session.execute(sql_delete(DbEdge).where(DbEdge.src_id == eid))
        await session.execute(sql_delete(DbEdge).where(DbEdge.dst_id == eid))
        await session.delete(entity)


class CreateEdgeRequest(BaseModel):
    src_id: str
    dst_id: str
    edge_type_name: str


@app.post("/edges", status_code=201)
async def create_edge(body: CreateEdgeRequest):
    async with db_session() as session:
        etype = await session.scalar(select(DbEdgeType).where(DbEdgeType.name == body.edge_type_name))
        if not etype:
            raise HTTPException(status_code=404, detail=f"Edge type {body.edge_type_name!r} not found")
        existing = await session.scalar(
            select(DbEdge).where(
                DbEdge.src_id == uuid.UUID(body.src_id),
                DbEdge.dst_id == uuid.UUID(body.dst_id),
                DbEdge.edge_type_id == etype.id,
            )
        )
        if existing:
            raise HTTPException(status_code=409, detail="Edge already exists")
        edge = DbEdge(src_id=uuid.UUID(body.src_id), dst_id=uuid.UUID(body.dst_id), edge_type_id=etype.id)
        session.add(edge)
        await session.flush()
        return {"id": str(edge.id), "src": str(edge.src_id), "dst": str(edge.dst_id), "type": etype.name, "derived": False}


@app.delete("/edges/{edge_id}", status_code=204)
async def delete_edge(edge_id: str):
    async with db_session() as session:
        edge = await session.get(DbEdge, uuid.UUID(edge_id))
        if not edge:
            raise HTTPException(status_code=404, detail="Edge not found")
        await session.delete(edge)


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


@app.get("/runs/{run_id}/trace")
async def get_run_trace(run_id: str):
    rid = uuid.UUID(run_id)
    async with db_session() as session:
        wrote = (
            await session.execute(
                select(DbEntity, DbOntologyType)
                .join(DbOntologyType, DbEntity.type_id == DbOntologyType.id)
                .where(DbEntity.created_in_run_id == rid)
            )
        ).all()

        tool_calls = (
            await session.execute(
                select(DbToolCall)
                .where(DbToolCall.run_id == rid)
                .order_by(DbToolCall.created_at)
            )
        ).scalars().all()

        delegations = (
            await session.execute(
                select(DbDelegation).where(DbDelegation.parent_run_id == rid)
            )
        ).scalars().all()

        return {
            "run_id": run_id,
            "wrote": [
                {
                    "id": str(e.id),
                    "type": ot.name,
                    "name": _entity_display_name(e.properties or {}, e.id),
                    "properties": e.properties or {},
                }
                for e, ot in wrote
            ],
            "tool_calls": [
                {
                    "tool": tc.tool_name,
                    "args": tc.tool_input or {},
                    "created_at": tc.created_at.isoformat(),
                }
                for tc in tool_calls
            ],
            "delegations": [
                {
                    "id": str(d.id),
                    "to_agent_spec_id": str(d.to_agent_spec_id),
                    "status": d.status,
                    "task_entity_id": str(d.task_entity_id) if d.task_entity_id else None,
                }
                for d in delegations
            ],
        }


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
            from claude_agent_sdk.types import ResultMessage
            from spec_factory import begin_run, build_options_from_spec, end_run, get_agent_entity_id, load_spec

            async with db_session() as session:
                spec = await load_spec(session, uuid.UUID(body.agent_id))
                agent_entity_id = await get_agent_entity_id(session, spec.id)
                task_uuid = uuid.UUID(body.task_id) if body.task_id else None
                run_ctx = await begin_run(session, body.message, spec, agent_entity_id, task_id=task_uuid)

                # Find the most recent session_id for this task to resume conversation history
                prior_session_id: str | None = None
                if task_uuid:
                    prior_run = await session.scalar(
                        select(DbRun)
                        .where(
                            DbRun.in_service_of_task_id == task_uuid,
                            DbRun.session_id.isnot(None),
                            DbRun.id != run_ctx.run_id,
                        )
                        .order_by(DbRun.started_at.desc())
                        .limit(1)
                    )
                    if prior_run:
                        prior_session_id = prior_run.session_id

            streaming_hook = await _make_streaming_hook(queue)

            options = build_options_from_spec(
                spec, run_ctx,
                streaming_hook=streaming_hook,
                permission_mode="bypassPermissions",
                resume_session_id=prior_session_id,
            )

            sdk_messages = []
            new_session_id: str | None = None
            async for sdk_msg in query(prompt=body.message, options=options):
                sdk_messages.append(sdk_msg)
                if isinstance(sdk_msg, AssistantMessage):
                    text = " ".join(
                        b.text for b in sdk_msg.content if isinstance(b, TextBlock)
                    ).strip()
                    if text:
                        await queue.put(("message", {"role": "agent", "content": text}))
                elif isinstance(sdk_msg, ResultMessage):
                    new_session_id = sdk_msg.session_id

            async with db_session() as session:
                session.add(
                    DbMessage(
                        run_id=run_ctx.run_id,
                        role="user",
                        content={"text": body.message, "tool_calls": []},
                    )
                )
                await session.flush()
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
                await end_run(session, run_ctx, sdk_messages)
                if new_session_id:
                    run = await session.get(DbRun, run_ctx.run_id)
                    if run:
                        run.session_id = new_session_id

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
    from builder_agent import capabilities_to_tools, sync_agent_to_ontology  # noqa: PLC0415
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
        result = _spec_to_dict(spec)
        spec_id = spec.id

    asyncio.create_task(sync_agent_to_ontology(spec_id, body.name, body.system_prompt))
    return result


class UpdateAgentRequest(BaseModel):
    name: str | None = None
    system_prompt: str | None = None
    capabilities: list[str] | None = None


@app.patch("/agents/{agent_id}")
async def update_agent(agent_id: str, body: UpdateAgentRequest):
    from builder_agent import capabilities_to_tools, sync_agent_to_ontology  # noqa: PLC0415
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
        result = _spec_to_dict(spec)
        spec_id, final_name, final_prompt = spec.id, spec.name, spec.system_prompt

    asyncio.create_task(sync_agent_to_ontology(spec_id, final_name, final_prompt))
    return result


@app.delete("/agents/{agent_id}", status_code=204)
async def delete_agent(agent_id: str):
    async with db_session() as session:
        aid = uuid.UUID(agent_id)
        spec = await session.get(DbAgentSpec, aid)
        if not spec:
            raise HTTPException(status_code=404, detail="Agent not found")
        run_ids_q = select(DbRun.id).where(DbRun.spec_id == aid)
        run_ids = (await session.execute(run_ids_q)).scalars().all()
        if run_ids:
            await session.execute(sql_update(DbEntity).where(DbEntity.created_in_run_id.in_(run_ids)).values(created_in_run_id=None))
            await session.execute(sql_update(DbEdge).where(DbEdge.created_in_run_id.in_(run_ids)).values(created_in_run_id=None))
            await session.execute(sql_delete(DbToolCall).where(DbToolCall.run_id.in_(run_ids)))
            await session.execute(sql_delete(DbMessage).where(DbMessage.run_id.in_(run_ids)))
        await session.execute(sql_delete(DbDelegation).where(DbDelegation.to_agent_spec_id == aid))
        await session.execute(sql_delete(DbRun).where(DbRun.spec_id == aid))
        await session.delete(spec)


# ---------------------------------------------------------------------------
# Policy CRUD
# ---------------------------------------------------------------------------

def _policy_row(p: DbPolicyRule) -> dict:
    return {
        "id": str(p.id),
        "name": p.name,
        "tool_pattern": p.tool_pattern,
        "subject_key": p.subject_key,
        "subject_type": p.subject_type,
        "blocking_conditions": p.blocking_conditions or [],
        "enabled": p.enabled,
        "created_at": p.created_at.isoformat(),
    }


@app.get("/policies")
async def list_policies():
    async with db_session() as session:
        rows = (await session.execute(select(DbPolicyRule).order_by(DbPolicyRule.created_at))).scalars().all()
        return [_policy_row(r) for r in rows]


class GeneratePolicyRequest(BaseModel):
    description: str


@app.post("/policies/generate")
async def generate_policy_endpoint(body: GeneratePolicyRequest):
    from policy_builder import generate_policy  # noqa: PLC0415

    tools = await list_tools()
    async with db_session() as session:
        entity_type_rows = (await session.execute(select(DbOntologyType))).scalars().all()
        edge_type_rows = (await session.execute(select(DbEdgeType))).scalars().all()
    entity_types = [{"name": t.name} for t in entity_type_rows]
    edge_types = [{"name": t.name} for t in edge_type_rows]
    return await generate_policy(body.description, tools, entity_types, edge_types)


class BlockingConditionModel(BaseModel):
    edge_type: str
    target_type: str | None = None
    blocking_target_states: dict[str, list[Any]] = {}
    message_template: str = "{subject} has active {edge_type} relationship(s)"
    invert: bool = False


class CreatePolicyRequest(BaseModel):
    name: str
    tool_pattern: str
    subject_key: str = ""
    subject_type: str = ""
    subject_source: str = "tool_input"
    tool_input_filter: dict[str, Any] | None = None
    blocking_conditions: list[BlockingConditionModel] = []


@app.post("/policies", status_code=201)
async def create_policy(body: CreatePolicyRequest):
    async with db_session() as session:
        rule = DbPolicyRule(
            name=body.name,
            tool_pattern=body.tool_pattern,
            subject_key=body.subject_key,
            subject_type=body.subject_type,
            subject_source=body.subject_source,
            tool_input_filter=body.tool_input_filter,
            blocking_conditions=[c.model_dump() for c in body.blocking_conditions],
            enabled=True,
        )
        session.add(rule)
        await session.flush()
        return _policy_row(rule)


class UpdatePolicyRequest(BaseModel):
    enabled: bool | None = None
    name: str | None = None


@app.patch("/policies/{policy_id}")
async def update_policy(policy_id: str, body: UpdatePolicyRequest):
    async with db_session() as session:
        rule = await session.get(DbPolicyRule, uuid.UUID(policy_id))
        if not rule:
            raise HTTPException(status_code=404, detail="Policy not found")
        if body.enabled is not None:
            rule.enabled = body.enabled
        if body.name is not None:
            rule.name = body.name
        await session.flush()
        return _policy_row(rule)


@app.delete("/policies/{policy_id}", status_code=204)
async def delete_policy(policy_id: str):
    async with db_session() as session:
        rule = await session.get(DbPolicyRule, uuid.UUID(policy_id))
        if not rule:
            raise HTTPException(status_code=404, detail="Policy not found")
        await session.delete(rule)
