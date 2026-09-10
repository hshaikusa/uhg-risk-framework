"""Summarize the newest demo/query run from normalized Phoenix spans."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any


def newest_span(spans: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not spans:
        return None

    def _key(span: dict[str, Any]) -> str:
        return str(span.get("start_time") or "")

    return max(spans, key=_key)


def parse_jsonish(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _as_dt(value: Any) -> datetime | None:
    try:
        if hasattr(value, "to_pydatetime"):
            value = value.to_pydatetime()
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if isinstance(value, datetime):
            return value
    except Exception:  # noqa: BLE001
        return None
    return None


def latest_run_spans(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Spans for the newest app run (LangGraph trace + nearby orphan LLM spans)."""
    preferred_names = {
        "LangGraph",
        "parse_query",
        "generate_narrative",
        "run_scenario",
        "compute_baseline",
        "mcp.call_tool",
        "tavily.search",
        "route_after_parse",
        "route_after_access",
        "check_access",
    }
    preferred = [s for s in spans if s.get("name") in preferred_names]
    anchor = newest_span(preferred) or newest_span(spans)
    if not anchor:
        return []

    trace_id = anchor.get("trace_id")
    trace_spans = [s for s in spans if trace_id and s.get("trace_id") == trace_id]
    anchor_ts = _as_dt(anchor.get("start_time"))
    if anchor_ts is None:
        return trace_spans

    nearby = []
    for span in spans:
        if span in trace_spans:
            continue
        if span.get("name") not in {
            "ChatCompletion",
            "instructor.patch",
            "handle_response_model",
        }:
            continue
        st = _as_dt(span.get("start_time"))
        if st is None:
            continue
        if abs((st - anchor_ts).total_seconds()) <= 30:
            nearby.append(span)
    return trace_spans + nearby


def summarize_latest_run(spans: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Extract a human-readable summary of the newest demo/query trace."""
    run_spans = latest_run_spans(spans)
    if not run_spans:
        return None

    preferred_names = {
        "LangGraph",
        "parse_query",
        "generate_narrative",
        "run_scenario",
        "compute_baseline",
        "mcp.call_tool",
        "tavily.search",
    }
    preferred = [s for s in run_spans if s.get("name") in preferred_names]
    anchor = newest_span(preferred) or newest_span(run_spans)
    if not anchor:
        return None

    names = sorted({str(s.get("name") or "") for s in run_spans})
    question = None
    audience = None
    narrative = None
    pathway = None
    segment = None
    for span in run_spans:
        inp = parse_jsonish(span.get("input_value"))
        out = span.get("output_value")
        if isinstance(inp, dict):
            question = question or inp.get("question")
            audience = audience or inp.get("audience")
            if isinstance(inp.get("scenario"), dict):
                pathway = pathway or inp["scenario"].get("recommended_pathway")
                segment = segment or inp["scenario"].get("segment")
            if "segment" in inp and not segment:
                segment = inp.get("segment")
        if span.get("name") == "generate_narrative" and out:
            parsed_out = parse_jsonish(out)
            if isinstance(parsed_out, dict):
                narrative = (
                    parsed_out.get("text")
                    or parsed_out.get("narrative")
                    or str(out)[:400]
                )
            else:
                narrative = str(out)[:400]
        if span.get("name") == "run_scenario" and out:
            parsed_out = parse_jsonish(out)
            if isinstance(parsed_out, dict):
                pathway = pathway or parsed_out.get("recommended_pathway")
                segment = segment or parsed_out.get("segment")

    return {
        "trace_id": anchor.get("trace_id"),
        "start_time": str(anchor.get("start_time")),
        "anchor_span": anchor.get("name"),
        "question": question,
        "segment": segment,
        "audience": audience,
        "recommended_pathway": pathway,
        "narrative_preview": narrative,
        "span_names": names,
        "span_count": len(run_spans),
        "kinds": sorted({str(s.get("span_kind") or "") for s in run_spans}),
    }
