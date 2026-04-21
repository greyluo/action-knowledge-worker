import pytest
from unittest.mock import AsyncMock, patch, MagicMock


async def test_llm_extract_returns_validated_result():
    from ontologist import llm_extract, ExtractionResult

    mock_response = MagicMock()
    mock_response.content = [MagicMock()]
    mock_response.content[0].text = '{"entities": [{"name": "Alice Chen", "properties": {"email": "alice@acme.com", "role": "VP of Sales"}, "type_hint": "Person"}], "relationships": []}'

    with patch("ontologist.anthropic_client") as mock_client:
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        result = await llm_extract(
            tool_output={"employees": [{"name": "Alice Chen", "email": "alice@acme.com"}]},
            ontology_summary="Existing types: Entity, Agent, Run, Task",
        )

    assert isinstance(result, ExtractionResult)
    assert len(result.entities) == 1
    assert result.entities[0].properties.get("email") == "alice@acme.com"


async def test_llm_extract_retries_on_invalid_json():
    from ontologist import llm_extract

    bad_response = MagicMock()
    bad_response.content = [MagicMock()]
    bad_response.content[0].text = "not valid json"

    good_response = MagicMock()
    good_response.content = [MagicMock()]
    good_response.content[0].text = '{"entities": [], "relationships": []}'

    with patch("ontologist.anthropic_client") as mock_client:
        mock_client.messages.create = AsyncMock(side_effect=[bad_response, good_response])
        result = await llm_extract(tool_output={}, ontology_summary="")

    assert result.entities == []
    assert mock_client.messages.create.call_count == 2
