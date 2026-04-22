"""Policy generator: single-call LLM spec generator from natural language."""
import json

import anthropic

_SYSTEM = """You are a policy spec generator for a graph-based AI governance system.

Policies intercept agent tool calls. Two modes:

HARM-PREVENTION (subject_source="tool_input", invert=false):
1. The policy reads tool_input[subject_key] to get an entity name
2. It looks up that entity by subject_type in the graph
3. If the entity has edges of edge_type to targets in blocking_target_states, the call is blocked
Example: block terminate_employee if the employee has assigned_to → Project{status="active"}

ACCESS-CONTROL (subject_source="actor", invert=true):
1. The subject is the calling agent itself (no subject_key lookup needed)
2. The call is blocked if the agent LACKS a has_permission edge to a Permission entity
   whose resource_type matches the protected resource.
Example: only library agents may access Books →
  edge_type=has_permission, target_type=Permission,
  blocking_target_states={resource_type: ["Book"]}, invert=true
Never use entity type names directly as edge targets for access control — always
gate through a Permission entity with a resource_type property.

Rules:
- Output ONLY a valid JSON object — no markdown, no explanation, no extra text.
- Use only entity type names and edge type names from the lists provided.
- Use the bare tool name (no mcp__prefix__ prefix) in tool_pattern.
- blocking_conditions must have at least one entry.
- For access-control policies: set subject_source="actor", invert=true, omit subject_key/subject_type.
- For harm-prevention policies: set subject_source="tool_input" (or omit), invert=false (or omit).
- Use tool_input_filter when the policy should only apply to a subset of calls to the matched
  tool — e.g. query_graph with entity_type="Book". Omit when the policy applies to all calls."""

_SCHEMA = """\
{
  "name": "<short policy name>",
  "tool_pattern": "<bare tool name or regex, e.g. terminate_employee>",
  "tool_input_filter": {"<param>": "<value>"},
  "subject_source": "<tool_input | actor>",
  "subject_key": "<parameter name from the matched tool — omit if subject_source=actor>",
  "subject_type": "<entity type name — omit if subject_source=actor>",
  "blocking_conditions": [
    {
      "edge_type": "<edge type name from the list>",
      "target_type": "<entity type name or null>",
      "blocking_target_states": {"<property>": ["<blocking value>"]},
      "invert": "<false to block when edge present; true to block when edge absent>",
      "message_template": "<message; use {subject}, {count}, {targets} as placeholders>"
    }
  ]
}"""


async def generate_policy(
    description: str,
    tools: list[dict],
    entity_types: list[dict],
    edge_types: list[dict],
) -> dict:
    tools_brief = [
        {"name": t["name"].split("__")[-1], "parameters": t["parameters"]}
        for t in tools
    ]
    context = (
        f"Available tools:\n{json.dumps(tools_brief, indent=2)}\n\n"
        f"Available entity types:\n{json.dumps([t['name'] for t in entity_types], indent=2)}\n\n"
        f"Available edge types:\n{json.dumps([e['name'] for e in edge_types], indent=2)}\n\n"
        f"Output schema (fill in the placeholders):\n{_SCHEMA}\n\n"
        f"Policy to generate: {description}"
    )

    client = anthropic.AsyncAnthropic()
    for attempt in range(2):
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=_SYSTEM,
            messages=[{"role": "user", "content": context}],
        )
        raw = response.content[0].text.strip()
        try:
            brace = raw.index("{")
            end = raw.rindex("}") + 1
            return json.loads(raw[brace:end])
        except (ValueError, json.JSONDecodeError):
            if attempt == 1:
                raise ValueError(f"Failed to parse policy JSON after 2 attempts. Raw: {raw!r}")
    raise RuntimeError("unreachable")
