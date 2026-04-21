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

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

def test_generate_spec_returns_parsed_dict():
    mock_text = '{"name": "Web Scout", "system_prompt": "You search the web.", "capabilities": ["web_research"]}'

    mock_content = MagicMock()
    mock_content.text = mock_text

    mock_response = MagicMock()
    mock_response.content = [mock_content]

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    with patch("builder_agent.anthropic.AsyncAnthropic", return_value=mock_client):
        from builder_agent import generate_spec
        result = asyncio.run(generate_spec("search the web for news"))

    assert result["name"] == "Web Scout"
    assert result["capabilities"] == ["web_research"]

def test_generate_spec_retries_on_bad_json():
    bad_text = "Sorry, I cannot do that."
    good_text = '{"name": "Scout", "system_prompt": "You search.", "capabilities": []}'

    call_count = 0

    async def mock_create(**kwargs):
        nonlocal call_count
        call_count += 1
        m = MagicMock()
        m.content = [MagicMock(text=bad_text if call_count == 1 else good_text)]
        return m

    mock_client = MagicMock()
    mock_client.messages.create = mock_create

    with patch("builder_agent.anthropic.AsyncAnthropic", return_value=mock_client):
        from builder_agent import generate_spec
        result = asyncio.run(generate_spec("do something"))

    assert call_count == 2
    assert result["name"] == "Scout"
