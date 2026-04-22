"""Mock MCP server with canned tool responses for demo agent.

Provides fetch_company_data, fetch_email_thread, and query_graph tools.
Canned data deliberately overlaps: Alice Chen (alice@acme.com) appears in
both Acme Corp employees, Globex Corp contacts, and email thread participants.
The "Acme Renewal 2026" deal appears in both company data and thread_001.
"""

import asyncio
import json
import uuid as _uuid_mod
from datetime import datetime, timezone
from typing import Any

from claude_agent_sdk import ToolAnnotations, create_sdk_mcp_server, tool

# ---------------------------------------------------------------------------
# Canned data
# ---------------------------------------------------------------------------

COMPANY_DATA: dict[str, Any] = {
    "TechStartup": {
        "company": {"name": "TechStartup", "domain": "techstartup.io", "industry": "Software"},
        "employees": [
            {
                "name": "Alex Johnson",
                "email": "alex@techstartup.io",
                "role": "Lead Developer",
                "assigned_project": "Mobile App Redesign",
            },
            {"name": "Maria Santos", "email": "maria@techstartup.io", "role": "HR Manager"},
        ],
        "projects": [
            {
                "name": "Mobile App Redesign",
                "status": "pending",
                "description": "Critical Q4 product launch — blocked by terminating lead",
                "lead": "Alex Johnson",
                "deadline": "2026-12-31",
            }
        ],
    },
    "Acme Corp": {
        "company": {"name": "Acme Corp", "domain": "acme.com", "industry": "Manufacturing"},
        "employees": [
            {"name": "Alice Chen", "email": "alice@acme.com", "role": "VP of Sales"},
            {"name": "Bob Martinez", "email": "bob@acme.com", "role": "Account Manager"},
        ],
        "deals": [
            {
                "name": "Acme Renewal 2026",
                "company": "Acme Corp",
                "value": 150000,
                "status": "negotiating",
            },
        ],
    },
    "Globex Corp": {
        "company": {"name": "Globex Corp", "domain": "globex.com", "industry": "Technology"},
        "employees": [
            {"name": "Carol Kim", "email": "carol@globex.com", "role": "CEO"},
        ],
        "contacts": [
            {"name": "Alice Chen", "email": "alice@acme.com", "role": "Partner Contact"},
        ],
        "deals": [
            {
                "name": "Globex Platform Deal",
                "company": "Globex Corp",
                "value": 250000,
                "status": "proposal",
            },
        ],
    },
}

EMAIL_THREADS: dict[str, Any] = {
    "thread_001": {
        "subject": "Re: Acme Renewal 2026 - Discount Discussion",
        "participants": [
            {"email": "alice@acme.com", "name": "Alice Chen"},
            {"email": "you@company.com", "name": "Sales Rep"},
        ],
        "messages": [
            {
                "from": "alice@acme.com",
                "body": (
                    "Hi, we're interested in renewing but need a 10% discount "
                    "to get approval from Bob Martinez."
                ),
            }
        ],
        "mentioned_deals": ["Acme Renewal 2026"],
        "mentioned_people": ["Bob Martinez"],
    },
    "thread_002": {
        "subject": "Globex Platform - Initial Discussion",
        "participants": [
            {"email": "carol@globex.com", "name": "Carol Kim"},
        ],
        "messages": [
            {
                "from": "carol@globex.com",
                "body": (
                    "We need the platform running before Q3. "
                    "Alice Chen at Acme recommended you."
                ),
            }
        ],
        "mentioned_deals": ["Globex Platform Deal"],
        "mentioned_people": ["Alice Chen"],
    },
    "thread_003": {
        "subject": "Acme Corp — Q2 Check-In",
        "participants": [
            {"email": "bob@acme.com", "name": "Bob Martinez"},
        ],
        "messages": [
            {
                "from": "bob@acme.com",
                "body": (
                    "Alice flagged the renewal. Can we schedule a call this week to discuss pricing?"
                ),
            }
        ],
        "mentioned_deals": ["Acme Renewal 2026"],
        "mentioned_people": ["Alice Chen"],
    },
}

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


@tool(
    "fetch_company_data",
    "Fetch CRM data for a named company: employees, contacts, and open deals.",
    {"company_name": str},
    annotations=ToolAnnotations(readOnlyHint=True),
)
async def fetch_company_data(args: dict[str, Any]) -> dict[str, Any]:
    company_name: str = args.get("company_name", "")
    data = COMPANY_DATA.get(company_name)
    if data is None:
        result = {"error": f"No data for company: {company_name!r}"}
    else:
        result = data
    return {"content": [{"type": "text", "text": json.dumps(result)}]}


@tool(
    "fetch_email_thread",
    "Fetch an email thread by thread ID. Returns participants, messages, and mentioned entities.",
    {"thread_id": str},
    annotations=ToolAnnotations(readOnlyHint=True),
)
async def fetch_email_thread(args: dict[str, Any]) -> dict[str, Any]:
    thread_id: str = args.get("thread_id", "")
    data = EMAIL_THREADS.get(thread_id)
    if data is None:
        result = {"error": f"No thread found: {thread_id!r}"}
    else:
        result = data
    return {"content": [{"type": "text", "text": json.dumps(result)}]}


@tool(
    "terminate_employee",
    (
        "Terminate an employee's contract. This is a destructive, irreversible action. "
        "Before calling this tool, verify there are no blocking constraints (e.g. active project assignments)."
    ),
    {"employee_name": str, "reason": str},
    annotations=ToolAnnotations(readOnlyHint=False),
)
async def terminate_employee(args: dict[str, Any]) -> dict[str, Any]:
    name: str = args.get("employee_name", "")
    reason: str = args.get("reason", "")
    result = {
        "status": "terminated",
        "employee": name,
        "reason": reason,
        "message": f"{name}'s contract has been terminated.",
    }
    return {"content": [{"type": "text", "text": json.dumps(result)}]}


@tool(
    "remember_entity",
    (
        "Persist a fact about a person, company, or deal to ontology. "
        "Call this when the user provides information that should be remembered "
        "(e.g. a name change, a new contact, an updated deal status). "
    ),
    {"name": str, "type_hint": str, "properties": dict},
    annotations=ToolAnnotations(readOnlyHint=False),
)
async def remember_entity(args: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(args)}]}


@tool(
    "query_graph",
    (
        "Query Ontology for typed entities and their relationships. "
        "Use this to look up previously discovered companies, people, deals, and tasks "
        "before making decisions."
    ),
    {
        "entity_type": str,
        "properties": dict,
        "related_to": str,
        "edge_types": list,
        "max_hops": int,
        "apply_inference": bool,
    },
    annotations=ToolAnnotations(readOnlyHint=True),
)
async def query_graph_tool(args: dict[str, Any]) -> dict[str, Any]:
    try:
        from query_graph import execute_query_graph  # noqa: PLC0415 — lazy import

        result = await execute_query_graph(
            entity_type=args.get("entity_type"),
            properties=args.get("properties"),
            related_to=args.get("related_to"),
            edge_types=args.get("edge_types"),
            max_hops=args.get("max_hops", 1),
            apply_inference=args.get("apply_inference", True),
        )
    except ImportError:
        result = {"error": "query_graph not available"}
    return {"content": [{"type": "text", "text": json.dumps(result)}]}


# ---------------------------------------------------------------------------
# delegate_task — requires run_ctx, so not part of module-level demo_server
# ---------------------------------------------------------------------------


async def _run_child_agent(
    to_agent_spec_id: str,
    task_prompt: str,
    child_task_id,
    parent_run_id,
    delegation_id,
    context_entity_ids: list,
) -> dict:
    """Spawn a child agent run and update the delegation row on completion."""
    from claude_agent_sdk import query  # noqa: PLC0415
    from db import AgentSpec, Delegation, Entity, db_session  # noqa: PLC0415
    from spec_factory import begin_run, build_options_from_spec, end_run, get_agent_entity_id  # noqa: PLC0415

    async with db_session() as session:
        spec_uuid = _uuid_mod.UUID(to_agent_spec_id) if isinstance(to_agent_spec_id, str) else to_agent_spec_id
        spec = await session.get(AgentSpec, spec_uuid)
        if not spec:
            return {"error": f"AgentSpec {to_agent_spec_id!r} not found"}
        agent_entity_id = await get_agent_entity_id(session, spec.id)
        run_ctx = await begin_run(
            session,
            task_prompt,
            spec,
            agent_entity_id,
            task_id=child_task_id,
            parent_run_id=parent_run_id,
            context_entity_ids=context_entity_ids,
        )

    options = build_options_from_spec(spec, run_ctx, permission_mode="bypassPermissions")

    sdk_messages: list = []
    async for msg in query(prompt=task_prompt, options=options):
        sdk_messages.append(msg)

    async with db_session() as session:
        from sqlalchemy import select as _select  # noqa: PLC0415
        await end_run(session, run_ctx, sdk_messages)

        produced_ids = (
            await session.execute(
                _select(Entity.id).where(Entity.created_in_run_id == run_ctx.run_id)
            )
        ).scalars().all()

        delegation = await session.get(Delegation, delegation_id)
        if delegation:
            delegation.status = "completed"
            delegation.child_run_id = run_ctx.run_id
            delegation.completed_at = datetime.now(timezone.utc)

    return {
        "delegation_id": str(delegation_id),
        "task_entity_id": str(child_task_id),
        "status": "completed",
        "produced_entity_ids": [str(eid) for eid in produced_ids],
    }


async def _delegate_task_impl(args: dict, run_ctx, *, _session=None) -> dict:
    """Core logic for delegate_task. Separated for testability.

    Pass _session in tests to reuse the test transaction instead of opening a
    new connection to the production database.
    """
    from sqlalchemy import select as _select  # noqa: PLC0415
    from db import (  # noqa: PLC0415
        AgentSpec, Delegation, Edge, EdgeType, Entity, OntologyType,
        db_session as _db_session,
    )
    from contextlib import asynccontextmanager  # noqa: PLC0415

    @asynccontextmanager
    async def _get_session():
        if _session is not None:
            yield _session
        else:
            async with _db_session() as s:
                yield s

    to_agent_spec_id: str = args.get("to_agent_id", "")
    task_prompt: str = args.get("task_prompt", "")
    context_entity_ids: list = args.get("context_entity_ids") or []
    execution_mode: str = args.get("execution_mode", "wait")
    handoff_summary: str = args.get("handoff_summary", "")

    async with _get_session() as session:
        try:
            target_uuid = _uuid_mod.UUID(to_agent_spec_id)
        except (ValueError, AttributeError):
            return {"error": f"Invalid agent ID: {to_agent_spec_id!r}"}

        target_spec = await session.get(AgentSpec, target_uuid)
        if not target_spec:
            return {"error": f"AgentSpec {to_agent_spec_id!r} not found"}

        agent_type = await session.scalar(
            _select(OntologyType).where(OntologyType.name == "Agent")
        )
        if not agent_type:
            return {"error": "Agent ontology type not found — run seed first"}

        calling_agent = await session.scalar(
            _select(Entity).where(
                Entity.type_id == agent_type.id,
                Entity.properties["spec_id"].astext == str(run_ctx.spec.id),
            )
        )
        target_agent = await session.scalar(
            _select(Entity).where(
                Entity.type_id == agent_type.id,
                Entity.properties["spec_id"].astext == str(target_uuid),
            )
        )

        if not calling_agent or not target_agent:
            return {"error": "Agent entities not found in ontology — run seed first"}

        del_et = await session.scalar(
            _select(EdgeType).where(EdgeType.name == "delegates_to")
        )
        if not del_et:
            return {"error": "delegates_to edge type not seeded"}

        existing_edge = await session.scalar(
            _select(Edge).where(
                Edge.src_id == calling_agent.id,
                Edge.dst_id == target_agent.id,
                Edge.edge_type_id == del_et.id,
            )
        )
        if not existing_edge:
            return {
                "error": (
                    f"No delegates_to edge from {run_ctx.spec.name!r} to "
                    f"{target_spec.name!r}. Add this edge in the Topology panel first."
                )
            }

        task_type = await session.scalar(
            _select(OntologyType).where(OntologyType.name == "Task")
        )
        part_of_et = await session.scalar(
            _select(EdgeType).where(EdgeType.name == "part_of")
        )
        seeded_with_et = await session.scalar(
            _select(EdgeType).where(EdgeType.name == "seeded_with")
        )

        child_task = Entity(
            type_id=task_type.id,
            properties={
                "title": task_prompt[:80],
                "description": task_prompt,
                "status": "pending",
                "outcome_summary": None,
            },
            source_refs=[{"delegated_by": str(run_ctx.run_id)}],
            created_by_agent_id=run_ctx.agent_entity_id,
            created_in_run_id=run_ctx.run_id,
        )
        session.add(child_task)
        await session.flush()

        if run_ctx.task_id and part_of_et:
            session.add(Edge(
                src_id=child_task.id,
                dst_id=run_ctx.task_id,
                edge_type_id=part_of_et.id,
                created_by_agent_id=run_ctx.agent_entity_id,
                created_in_run_id=run_ctx.run_id,
            ))

        if seeded_with_et:
            for eid_str in context_entity_ids:
                try:
                    session.add(Edge(
                        src_id=child_task.id,
                        dst_id=_uuid_mod.UUID(eid_str),
                        edge_type_id=seeded_with_et.id,
                        created_by_agent_id=run_ctx.agent_entity_id,
                        created_in_run_id=run_ctx.run_id,
                    ))
                except (ValueError, AttributeError):
                    pass

        if handoff_summary:
            handoff_type = await session.scalar(
                _select(OntologyType).where(OntologyType.name == "Handoff")
            )
            in_service_et = await session.scalar(
                _select(EdgeType).where(EdgeType.name == "in_service_of")
            )
            if handoff_type and in_service_et:
                handoff_ent = Entity(
                    type_id=handoff_type.id,
                    properties={
                        "from_agent": str(run_ctx.agent_entity_id),
                        "to_agent": str(target_agent.id),
                        "summary": handoff_summary,
                        "key_entity_ids": context_entity_ids,
                    },
                    source_refs=[],
                    created_by_agent_id=run_ctx.agent_entity_id,
                    created_in_run_id=run_ctx.run_id,
                )
                session.add(handoff_ent)
                await session.flush()
                if run_ctx.task_id:
                    session.add(Edge(
                        src_id=handoff_ent.id,
                        dst_id=run_ctx.task_id,
                        edge_type_id=in_service_et.id,
                        created_by_agent_id=run_ctx.agent_entity_id,
                        created_in_run_id=run_ctx.run_id,
                    ))

        delegation = Delegation(
            parent_run_id=run_ctx.run_id,
            task_entity_id=child_task.id,
            to_agent_spec_id=target_uuid,
            context_ids=context_entity_ids,
            status="pending",
        )
        session.add(delegation)
        await session.flush()
        delegation_id = delegation.id
        child_task_id = child_task.id

    if execution_mode == "wait":
        return await _run_child_agent(
            to_agent_spec_id, task_prompt, child_task_id,
            run_ctx.run_id, delegation_id, context_entity_ids,
        )
    else:
        asyncio.create_task(
            _run_child_agent(
                to_agent_spec_id, task_prompt, child_task_id,
                run_ctx.run_id, delegation_id, context_entity_ids,
            )
        )
        return {
            "delegation_id": str(delegation_id),
            "task_entity_id": str(child_task_id),
            "status": "running",
        }


def make_demo_server(run_ctx=None):
    """Create an MCP server. If run_ctx provided, includes delegate_task."""
    tools_list = [
        fetch_company_data,
        fetch_email_thread,
        terminate_employee,
        remember_entity,
        query_graph_tool,
    ]

    if run_ctx is not None:
        @tool(
            "delegate_task",
            (
                "Delegate a subtask to another agent. The target agent must have a "
                "delegates_to edge from this agent in the ontology graph. "
                "Pass context_entity_ids to share relevant graph nodes with the child agent."
            ),
            {
                "to_agent_id": str,
                "task_prompt": str,
                "context_entity_ids": list,
                "execution_mode": str,
                "handoff_summary": str,
            },
        )
        async def delegate_task_tool(args: dict) -> dict:
            result = await _delegate_task_impl(args, run_ctx)
            return {"content": [{"type": "text", "text": json.dumps(result)}]}

        tools_list.append(delegate_task_tool)

    return create_sdk_mcp_server(
        name="demo",
        version="1.0.0",
        tools=tools_list,
    )


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

demo_server = make_demo_server()
