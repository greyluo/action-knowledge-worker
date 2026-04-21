import pytest
from builder_agent import capabilities_to_tools, tools_to_capabilities

def test_capabilities_to_tools_web_research():
    tools = capabilities_to_tools(["web_research"])
    assert tools == ["WebFetch", "WebSearch"]

def test_capabilities_to_tools_multiple():
    tools = capabilities_to_tools(["web_research", "shell"])
    assert "WebFetch" in tools
    assert "WebSearch" in tools
    assert "Bash" in tools

def test_capabilities_to_tools_unknown_slug_ignored():
    tools = capabilities_to_tools(["nonexistent"])
    assert tools == []

def test_capabilities_to_tools_empty():
    assert capabilities_to_tools([]) == []

def test_tools_to_capabilities_single():
    caps = tools_to_capabilities(["Bash"])
    assert caps == ["shell"]

def test_tools_to_capabilities_partial_match():
    caps = tools_to_capabilities(["WebFetch"])
    assert "web_research" in caps
    assert "shell" not in caps

def test_tools_to_capabilities_unknown_tool_ignored():
    caps = tools_to_capabilities(["UnknownTool"])
    assert caps == []

def test_tools_to_capabilities_empty():
    assert tools_to_capabilities([]) == []

def test_roundtrip():
    caps_in = ["web_research", "company_data"]
    tools = capabilities_to_tools(caps_in)
    caps_out = tools_to_capabilities(tools)
    assert set(caps_out) == set(caps_in)
