"""Mock MCP server with canned tool responses for demo agent.

Provides fetch_company_data, fetch_email_thread, and query_graph tools.
Canned data deliberately overlaps: Alice Chen (alice@acme.com) appears in
both Acme Corp employees, Globex Corp contacts, and email thread participants.
The "Acme Renewal 2026" deal appears in both company data and thread_001.
"""

import json
from typing import Any

from claude_agent_sdk import ToolAnnotations, create_sdk_mcp_server, tool

# ---------------------------------------------------------------------------
# Canned data
# ---------------------------------------------------------------------------

COMPANY_DATA: dict[str, Any] = {
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
    "remember_entity",
    (
        "Persist a fact about a person, company, or deal to the knowledge graph. "
        "Call this when the user provides information that should be remembered "
        "(e.g. a name change, a new contact, an updated deal status)."
    ),
    {"name": str, "type_hint": str, "properties": dict},
    annotations=ToolAnnotations(readOnlyHint=False),
)
async def remember_entity(args: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(args)}]}


@tool(
    "query_graph",
    (
        "Query the knowledge graph for typed entities and their relationships. "
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
# MCP server
# ---------------------------------------------------------------------------

demo_server = create_sdk_mcp_server(
    name="demo",
    version="1.0.0",
    tools=[fetch_company_data, fetch_email_thread, remember_entity, query_graph_tool],
)
