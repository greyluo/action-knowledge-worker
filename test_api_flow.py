"""
End-to-end test: builder creates a spec → /chat runs it → ontology populated.

Steps:
  1. POST /builder/generate → POST /agents to create spec
  2. POST /chat with the new agent_id → stream the run
  3. Query the DB directly to verify entities were created by the Stop hook
"""
import asyncio
import json
import sys

import httpx

BASE = "http://127.0.0.1:8000"


def parse_sse(text: str) -> list[dict]:
    events = []
    current = {}
    for line in text.splitlines():
        if line.startswith("event:"):
            current["event"] = line[6:].strip()
        elif line.startswith("data:"):
            try:
                current["data"] = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                current["data"] = line[5:].strip()
        elif line == "" and current:
            events.append(current)
            current = {}
    if current:
        events.append(current)
    return events


async def step1_create_spec() -> str:
    print("\n── Step 1: create agent spec via /builder/generate + /agents ──")
    description = (
        "Fetch company data and email threads about Acme Corp, "
        "then summarise what it finds."
    )
    async with httpx.AsyncClient(timeout=60) as client:
        gen_resp = await client.post(
            f"{BASE}/builder/generate",
            json={"description": description},
        )
        gen_resp.raise_for_status()
        spec_preview = gen_resp.json()
        print(f"  generated: {spec_preview}")

        create_resp = await client.post(
            f"{BASE}/agents",
            json={
                "name": spec_preview["name"],
                "system_prompt": spec_preview["system_prompt"],
                "capabilities": spec_preview.get("capabilities", []),
            },
        )
        create_resp.raise_for_status()
        saved = create_resp.json()

    spec_id = saved["id"]
    print(f"\n  ✓ spec created: {spec_id} — {saved['name']}")
    return spec_id


async def step2_run_agent(spec_id: str) -> dict:
    print("\n── Step 2: run agent via /chat ──")
    payload = {
        "agent_id": spec_id,
        "message": "Fetch information about Acme Corp and summarise what you find.",
    }
    events = []
    async with httpx.AsyncClient(timeout=180) as client:
        async with client.stream("POST", f"{BASE}/chat", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("event:"):
                    event_type = line[6:].strip()
                elif line.startswith("data:"):
                    try:
                        data = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        data = line[5:].strip()
                    ev = {"event": event_type, "data": data}
                    events.append(ev)
                    if event_type == "message":
                        print(f"  [agent] {str(data.get('content', ''))[:200]}")
                    elif event_type == "tool_call":
                        print(f"  [tool]  → {data.get('tool')}({str(data.get('args', ''))[:80]})")
                    elif event_type in ("done", "error"):
                        print(f"  [{event_type}] {data}")

    run_info = {}
    for ev in events:
        if ev.get("event") == "done":
            run_info = ev["data"]
    return run_info


async def step3_verify_ontology(run_info: dict):
    print("\n── Step 3: verify ontology via /entities ──")
    run_id = run_info.get("run_id")
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{BASE}/entities")
        resp.raise_for_status()
        entities = resp.json()

    if not entities:
        print("  FAIL: no entities in DB")
        sys.exit(1)

    by_type: dict[str, list] = {}
    for e in entities:
        by_type.setdefault(e["type"], []).append(e)

    print(f"\n  Total entities: {len(entities)}")
    for type_name, ents in sorted(by_type.items()):
        print(f"  {type_name}: {len(ents)}")
        for e in ents[:3]:
            name = e.get("name") or e["id"][:8]
            print(f"    • {name}")

    domain_types = {k for k in by_type if k not in ("Agent", "Run", "Task", "Entity")}
    if domain_types:
        print(f"\n  ✓ domain entity types created by Stop hook: {domain_types}")
    else:
        print("\n  ✗ no domain entities created — Stop hook may not have fired")
        sys.exit(1)


async def main():
    spec_id = await step1_create_spec()
    run_info = await step2_run_agent(spec_id)
    await step3_verify_ontology(run_info)
    print("\n── All steps passed ──\n")


if __name__ == "__main__":
    asyncio.run(main())
