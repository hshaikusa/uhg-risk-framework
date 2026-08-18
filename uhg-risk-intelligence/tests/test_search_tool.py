from unittest.mock import MagicMock, patch

from src.ai_steps.search_tool import search_for_overlay_input


@patch("src.ai_steps.search_tool.retriever_span")
@patch("src.ai_steps.search_tool._load_bundled_sample")
def test_search_uses_bundled_fallback_when_no_api_key(mock_sample, mock_span):
    span = MagicMock()
    mock_span.return_value.__enter__ = MagicMock(return_value=span)
    mock_span.return_value.__exit__ = MagicMock(return_value=False)
    mock_sample.return_value = {"id": "demo", "text": "fallback text"}

    with patch.dict("os.environ", {}, clear=True):
        text, label = search_for_overlay_input("cyber query", "Optum_Insight")

    assert text == "fallback text"
    assert label == "bundled_fallback:demo"
    mock_span.assert_called_once()


@patch("src.ai_steps.search_tool.set_span_output")
@patch("src.ai_steps.search_tool.retriever_span")
def test_search_emits_retriever_span_on_live_hit(mock_span, mock_set_output):
    span = MagicMock()
    mock_span.return_value.__enter__ = MagicMock(return_value=span)
    mock_span.return_value.__exit__ = MagicMock(return_value=False)

    mock_client = MagicMock()
    mock_client.search.return_value = {
        "results": [{"content": "live article body", "url": "https://example.com/article"}],
    }

    with patch.dict("os.environ", {"TAVILY_API_KEY": "test-key"}), \
         patch("tavily.TavilyClient", return_value=mock_client):
        text, label = search_for_overlay_input("cyber query", "Optum_Insight")

    assert text == "live article body"
    assert label == "https://example.com/article"
    span.set_attribute.assert_any_call("search.live", True)
    span.set_attribute.assert_any_call("search.source", "https://example.com/article")
    mock_set_output.assert_called_once()
