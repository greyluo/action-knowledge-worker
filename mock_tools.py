"""Stub MCP server with canned tool responses for demo agent.

Full implementation deferred to Task 5. Provides demo_server for spec_factory.
"""
from claude_agent_sdk import create_sdk_mcp_server

demo_server = create_sdk_mcp_server(name="demo", version="1.0.0", tools=[])
