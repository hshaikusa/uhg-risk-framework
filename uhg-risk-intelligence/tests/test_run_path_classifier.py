"""Path classifier unit tests (no Phoenix / API)."""

from evals.scorers.traces import classify_run_path, score_latest_run_path


def _span(name: str, *, kind: str = "CHAIN", output: str = "", status: str = "UNSET") -> dict:
    return {
        "name": name,
        "span_kind": kind,
        "status_code": status,
        "output_value": output,
        "input_value": "",
        "span_id": name,
    }


def test_full_success_path():
    spans = [
        _span("parse_query"),
        _span("check_access"),
        _span("compute_baseline"),
        _span("run_scenario"),
        _span("generate_narrative", kind="CHAIN"),
        _span("ChatCompletion", kind="LLM", output='{"text":"risk 72"}'),
    ]
    info = classify_run_path(spans)
    assert info["path"] == "full_success"
    scored = score_latest_run_path(spans)
    assert scored["passed"] is True


def test_overlay_success_with_retriever_and_extract():
    spans = [
        _span(
            "tavily.search",
            kind="RETRIEVER",
            output='{"live": true, "content_preview": "cyber incident Optum"}',
            status="UNSET",
        ),
        _span(
            "ChatCompletion",
            kind="LLM",
            output=(
                '{"choices":[{"message":{"tool_calls":[{"function":'
                '{"arguments":"{\\"sign\\":\\"risk\\",\\"severity_0_to_3\\":3,'
                '\\"immediacy_0_to_3\\":2,\\"persistence_0_to_3\\":2}"}}]}}]}'
            ),
            status="UNSET",
        ),
    ]
    info = classify_run_path(spans)
    assert info["path"] == "overlay_success"
    scored = score_latest_run_path(spans)
    assert scored["passed"] is True
    assert scored["path"] == "overlay_success"


def test_mcp_tool_path():
    spans = [
        _span(
            "mcp.call_tool",
            kind="TOOL",
            output='{"ok": true}',
            status="UNSET",
        ),
    ]
    # give tool I/O shape used by mcp scorer
    spans[0]["input_value"] = '{"tool":"local.list_schema"}'
    spans[0]["tool_name"] = "local.list_schema"
    info = classify_run_path(spans)
    assert info["path"] == "mcp_tool"
    assert score_latest_run_path(spans)["passed"] is True


def test_unknown_still_fails_when_noise_only():
    spans = [_span("ChatCompletion", kind="LLM", output='{"hello":1}')]
    info = classify_run_path(spans)
    assert info["path"] == "unknown"
    assert score_latest_run_path(spans)["passed"] is False
