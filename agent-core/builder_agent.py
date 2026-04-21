"""Builder agent: single-call spec generator with capability model."""
import json

import anthropic

CAPABILITIES: dict[str, list[str]] = {
    "web_research": ["WebFetch", "WebSearch"],
    "file_analysis": ["Read", "Write", "Edit", "Glob", "Grep"],
    "shell": ["Bash"],
    "company_data": ["mcp__demo__fetch_company_data", "mcp__demo__fetch_email_thread"],
}

CAPABILITY_LABELS: dict[str, str] = {
    "web_research": "Web research",
    "file_analysis": "File analysis",
    "shell": "Shell access",
    "company_data": "Company data",
}


def capabilities_to_tools(capabilities: list[str]) -> list[str]:
    tools: list[str] = []
    for slug in capabilities:
        tools.extend(CAPABILITIES.get(slug, []))
    return tools


def tools_to_capabilities(tools: list[str]) -> list[str]:
    tool_set = set(tools)
    return [
        slug
        for slug, slug_tools in CAPABILITIES.items()
        if any(t in tool_set for t in slug_tools)
    ]


_GENERATE_SYSTEM = """You are an agent spec generator. Given a description of what an agent should do, output a JSON object.

Available capabilities:
- web_research: Fetch web pages and search the internet
- file_analysis: Read, write, and search files on disk
- shell: Run shell commands
- company_data: Fetch company profiles and email threads

Output ONLY a JSON object with these exact keys (no markdown fences, no extra text):
{"name": "<2-4 word agent name>", "system_prompt": "<2-5 sentence focused system prompt>", "capabilities": ["<slug>", ...]}

Select only the capabilities genuinely needed. Omit any not relevant to the description."""


async def generate_spec(description: str) -> dict:
    client = anthropic.AsyncAnthropic()
    for attempt in range(2):
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=_GENERATE_SYSTEM,
            messages=[{"role": "user", "content": description}],
        )
        raw = response.content[0].text.strip()
        try:
            brace = raw.index("{")
            end = raw.rindex("}") + 1
            return json.loads(raw[brace:end])
        except (ValueError, json.JSONDecodeError):
            if attempt == 1:
                raise ValueError(f"Failed to parse spec JSON after 2 attempts. Raw: {raw}")
    raise RuntimeError("unreachable")
