from unittest.mock import MagicMock, patch

from src.mcp.client import parse_tool_arguments, parse_tool_ref
from src.mcp.config import load_server_configs


def test_parse_tool_ref():
    assert parse_tool_ref("local.list_schema") == ("local", "list_schema")


def test_default_local_server_configured():
    servers = load_server_configs()
    assert "local" in servers
    assert servers["local"].args[-1] == "src.mcp.local_server"


def test_parse_tool_arguments_flag_style():
    assert parse_tool_arguments(["--symbol", "UNH"]) == {"symbol": "UNH"}


def test_parse_tool_arguments_ticker_alias():
    assert parse_tool_arguments(["--ticker", "UNH"]) == {"symbol": "UNH"}
    assert parse_tool_arguments(["ticker=UNH"]) == {"symbol": "UNH"}


def test_parse_tool_arguments_arg_style():
    assert parse_tool_arguments(["--arg", "symbol=UNH"]) == {"symbol": "UNH"}
    assert parse_tool_arguments(["symbol=UNH"]) == {"symbol": "UNH"}


@patch("src.mcp.enrichment.call_tool")
def test_print_mcp_context_uses_local_fallback(mock_call):
    mock_call.return_value = '{"anchors": [{"id": "test", "description": "demo"}]}'
    from src.mcp.enrichment import print_mcp_context

    with patch("src.mcp.enrichment.load_server_configs", return_value={"local": MagicMock()}):
        print_mcp_context()
    mock_call.assert_called()


def test_search_via_mcp_or_fallback_uses_tavily_path_when_no_search_tools(
    monkeypatch,
):
    monkeypatch.setenv("MCP_ENABLED", "true")
    with patch("src.mcp.enrichment.list_all_tools", return_value=[]), \
         patch("src.mcp.enrichment.search_for_overlay_input",
               return_value=("sample text", "bundled_fallback:sample")) as mock_search:
        from src.mcp.enrichment import search_via_mcp_or_fallback
        text, label = search_via_mcp_or_fallback("cyber query", "Optum_Insight")
    assert text == "sample text"
    mock_search.assert_called_once()


def test_mcp_span_sets_string_kind(monkeypatch):
    monkeypatch.setenv("OBSERVABILITY_BACKEND", "phoenix")
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    from src.observability import mcp_span

    with mcp_span("mcp.call_tool", server="local", tool="list_schema", arguments={}):
        pass

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    attrs = dict(spans[0].attributes)
    assert attrs["openinference.span.kind"] == "TOOL"
    assert attrs["tool.name"] == "local.list_schema"


@patch("src.mcp.client.mcp_span")
def test_call_tool_emits_mcp_span(mock_mcp_span, monkeypatch):
    from contextlib import contextmanager

    @contextmanager
    def fake_span(*_args, **_kwargs):
        span = MagicMock()
        yield span

    mock_mcp_span.side_effect = fake_span
    monkeypatch.setenv("MCP_ENABLED", "true")

    async def fake_call(*_args, **_kwargs):
        return '{"ok": true}'

    with patch("src.mcp.client._call_tool_async", side_effect=fake_call), \
         patch("src.mcp.client.load_server_configs") as mock_configs:
        mock_configs.return_value = {
            "local": MagicMock(name="local", command="python", args=[], env=None, cwd=None),
        }
        from src.mcp.client import call_tool
        result = call_tool("local", "list_schema", {})
    assert result == '{"ok": true}'
    mock_mcp_span.assert_called_once()
    assert mock_mcp_span.call_args.kwargs["server"] == "local"
    assert mock_mcp_span.call_args.kwargs["tool"] == "list_schema"
