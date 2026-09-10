"""Eval scorers that operate on normalized observability spans."""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from evals.scorers.narrative import CAVEAT_MARKER
from evals.scorers.retrieval import score_retrieval_relevance


def _attr(span: dict[str, Any], *keys: str) -> Any:
    attrs = span.get("attributes") or {}
    for key in keys:
        if key in attrs and attrs[key] is not None:
            return attrs[key]
        dotted = key
        if dotted in attrs and attrs[dotted] is not None:
            return attrs[dotted]
    return None


def score_kind_coverage(
    spans: list[dict[str, Any]],
    required_kinds: tuple[str, ...] = ("LLM", "CHAIN", "TOOL", "RETRIEVER"),
) -> dict[str, Any]:
    kinds = Counter(s.get("span_kind") or "UNKNOWN" for s in spans)
    missing = [k for k in required_kinds if kinds.get(k, 0) == 0]
    # RETRIEVER/TOOL may be absent in a short window — soft-require LLM+CHAIN always.
    hard_missing = [k for k in ("LLM", "CHAIN") if kinds.get(k, 0) == 0]
    passed = not hard_missing
    score = 1.0 - (len(missing) / max(len(required_kinds), 1))
    return {
        "passed": passed,
        "score": round(max(0.0, score), 3),
        "counts": dict(kinds),
        "missing": missing,
        "hard_missing": hard_missing,
    }


def score_unknown_kind_rate(spans: list[dict[str, Any]], max_unknown_rate: float = 0.25) -> dict[str, Any]:
    if not spans:
        return {"passed": False, "score": 0.0, "unknown_rate": 1.0, "total": 0}
    unknown = sum(1 for s in spans if (s.get("span_kind") or "UNKNOWN") == "UNKNOWN")
    rate = unknown / len(spans)
    passed = rate <= max_unknown_rate
    return {
        "passed": passed,
        "score": round(1.0 - rate, 3),
        "unknown_rate": round(rate, 3),
        "unknown": unknown,
        "total": len(spans),
    }


def score_error_rate(spans: list[dict[str, Any]], max_error_rate: float = 0.1) -> dict[str, Any]:
    if not spans:
        return {"passed": False, "score": 0.0, "error_rate": 1.0}
    errors = sum(1 for s in spans if str(s.get("status_code")).upper() == "ERROR")
    rate = errors / len(spans)
    return {
        "passed": rate <= max_error_rate,
        "score": round(1.0 - rate, 3),
        "error_rate": round(rate, 3),
        "errors": errors,
        "total": len(spans),
    }


def score_retriever_traces(spans: list[dict[str, Any]]) -> dict[str, Any]:
    retrievers = [s for s in spans if s.get("span_kind") == "RETRIEVER" or s.get("name") == "tavily.search"]
    if not retrievers:
        return {
            "passed": True,
            "score": 1.0,
            "skipped": True,
            "detail": "no RETRIEVER spans in window",
        }
    results = []
    for span in retrievers:
        out = span.get("output_value") or ""
        inp = str(span.get("input_value") or "")
        has_io = bool(inp) and bool(out)
        live = None
        source = None
        preview = str(out)
        try:
            parsed = json.loads(out) if isinstance(out, str) and out.strip().startswith("{") else None
            if isinstance(parsed, dict):
                live = parsed.get("live")
                source = parsed.get("source")
                preview = parsed.get("content_preview") or preview
        except json.JSONDecodeError:
            parsed = None

        # Infer segment/driver cues from the search query when present.
        ql = inp.lower()
        segment, driver = "Optum_Health", "Capital"
        if "insight" in ql or "cyber" in ql or "security" in ql:
            segment, driver = "Optum_Insight", "Data_Digital"
        elif "rx" in ql:
            segment, driver = "Optum_Rx", "Supply"
        rel = score_retrieval_relevance(
            str(preview),
            segment=segment,
            driver=driver,
            expect_relevant=True,
        )
        # Observability pass: span is well-formed (kind/I/O/source). Relevance is soft.
        structural_ok = has_io and (source is not None or len(str(preview)) > 40)
        results.append(
            {
                "span_id": span.get("span_id"),
                "passed": structural_ok,
                "has_io": has_io,
                "live": live,
                "source": source,
                "relevance_predicted": rel["predicted_relevant"],
                "relevance": rel,
            }
        )
    passed_n = sum(1 for r in results if r["passed"])
    soft_rel = sum(1 for r in results if r.get("relevance_predicted"))
    return {
        "passed": passed_n == len(results),
        "score": round(passed_n / len(results), 3),
        "relevance_hit_rate": round(soft_rel / len(results), 3),
        "count": len(results),
        "results": results,
    }


def score_mcp_tool_traces(spans: list[dict[str, Any]]) -> dict[str, Any]:
    # Latest-run / watch: only score explicit MCP client spans. Generic OpenInference
    # TOOL kind spans (e.g. instructor tool-calls on overlay extract) are not MCP demos.
    tools = [s for s in spans if s.get("name") == "mcp.call_tool"]
    if not tools:
        return {
            "passed": True,
            "score": 1.0,
            "skipped": True,
            "detail": "no mcp.call_tool spans in window",
        }
    results = []
    for span in tools:
        tool_name = span.get("tool_name") or _attr(span, "tool.name", "mcp.tool")
        has_io = bool(span.get("input_value")) and bool(span.get("output_value"))
        status_ok = str(span.get("status_code")).upper() in {"OK", "UNSET"}
        ok = bool(tool_name) and has_io and status_ok
        results.append(
            {
                "span_id": span.get("span_id"),
                "tool_name": tool_name,
                "passed": ok,
                "has_io": has_io,
                "status_code": span.get("status_code"),
            }
        )
    passed_n = sum(1 for r in results if r["passed"])
    return {
        "passed": passed_n == len(results),
        "score": round(passed_n / len(results), 3),
        "count": len(results),
        "results": results,
    }


def score_guardrail_clarify_traces(spans: list[dict[str, Any]]) -> dict[str, Any]:
    """Fail-closed routing should appear as route_after_parse → clarify on out_of_scope."""
    routes = [s for s in spans if s.get("name") == "route_after_parse"]
    interesting = []
    for span in routes:
        inp = str(span.get("input_value") or "")
        out = str(span.get("output_value") or "")
        if "out_of_scope" in inp or "unknown_segment" in inp or "parse_failure" in inp:
            interesting.append(
                {
                    "span_id": span.get("span_id"),
                    "output": out,
                    "passed": out.strip() == "clarify",
                    "input_preview": inp[:240],
                }
            )
    if not interesting:
        return {
            "passed": True,
            "score": 1.0,
            "skipped": True,
            "detail": "no parse-failure route spans in window",
        }
    passed_n = sum(1 for r in interesting if r["passed"])
    return {
        "passed": passed_n == len(interesting),
        "score": round(passed_n / len(interesting), 3),
        "count": len(interesting),
        "results": interesting,
    }


def score_narrative_caveat_traces(spans: list[dict[str, Any]]) -> dict[str, Any]:
    """If a narrative LLM/chain output mentions low confidence, caveat marker should appear."""
    candidates = [
        s
        for s in spans
        if s.get("name") in {"generate_narrative", "ChatCompletion"} and s.get("output_value")
    ]
    checked = []
    for span in candidates:
        out = str(span.get("output_value") or "")
        inp = str(span.get("input_value") or "")
        # Only score when the scenario clearly signals low confidence.
        low_conf = bool(
            re.search(r'"confidence"\s*:\s*0\.[0-4]', inp)
            or re.search(r"confidence(?:\s*[:=]\s*)0\.[0-4]", inp, re.I)
            or "below_confidence_floor\": true" in inp
            or "below_confidence_floor': True" in inp
        )
        if not low_conf:
            continue
        checked.append(
            {
                "span_id": span.get("span_id"),
                "name": span.get("name"),
                "passed": CAVEAT_MARKER in out,
                "has_caveat": CAVEAT_MARKER in out,
            }
        )
    if not checked:
        return {
            "passed": True,
            "score": 1.0,
            "skipped": True,
            "detail": "no low-confidence narrative spans in window",
        }
    passed_n = sum(1 for r in checked if r["passed"])
    return {
        "passed": passed_n == len(checked),
        "score": round(passed_n / len(checked), 3),
        "count": len(checked),
        "results": checked,
    }


def score_graph_node_presence(spans: list[dict[str, Any]]) -> dict[str, Any]:
    """Happy-path LangGraph nodes should show up when query traces exist."""
    names = {s.get("name") for s in spans}
    expected = ("parse_query", "check_access", "compute_baseline", "run_scenario", "generate_narrative")
    # Only require full path if we saw parse_query succeed into access.
    if "parse_query" not in names:
        return {
            "passed": True,
            "score": 1.0,
            "skipped": True,
            "detail": "no parse_query spans in window",
        }
    present = [n for n in expected if n in names]
    # Soft: at least parse_query + one downstream deterministic/LLM node
    passed = "parse_query" in names and len(present) >= 2
    return {
        "passed": passed,
        "score": round(len(present) / len(expected), 3),
        "present": present,
        "missing": [n for n in expected if n not in names],
    }


def _has_overlay_extract(spans: list[dict[str, Any]]) -> bool:
    """True if a ChatCompletion / extract span embeds overlay ordinal ratings."""
    for span in spans:
        blob = str(span.get("output_value") or "")
        if "severity_0_to_3" in blob and ("immediacy_0_to_3" in blob or "persistence_0_to_3" in blob):
            return True
        name = str(span.get("name") or "")
        if "overlay" in name.lower():
            return True
    return False


def _has_retriever(spans: list[dict[str, Any]]) -> bool:
    return any(
        s.get("span_kind") == "RETRIEVER" or s.get("name") == "tavily.search" for s in spans
    )


def _has_mcp_tool(spans: list[dict[str, Any]]) -> bool:
    return any(
        s.get("name") == "mcp.call_tool" or str(s.get("name") or "").startswith("mcp.")
        for s in spans
    )


def classify_run_path(spans: list[dict[str, Any]]) -> dict[str, Any]:
    """Classify a single demo run from its spans (not the whole Phoenix window)."""
    names = {s.get("name") for s in spans}
    route_outs = [
        str(s.get("output_value") or "").strip()
        for s in spans
        if s.get("name") == "route_after_parse"
    ]
    access_outs = [
        str(s.get("output_value") or "").strip()
        for s in spans
        if s.get("name") == "route_after_access"
    ]

    # IMPORTANT: do not substring-match "parse_failure" in raw JSON — happy-path
    # LangGraph state often contains `"parse_failure": null`.
    clarify_route = any(o == "clarify" for o in route_outs)
    denied_route = any(o in {"denied", "access_denied"} or "access_denied" in o for o in access_outs)

    active_parse_failure = False
    for span in spans:
        inp = span.get("input_value")
        parsed = None
        if isinstance(inp, dict):
            parsed = inp
        elif isinstance(inp, str) and inp.strip().startswith("{"):
            try:
                parsed = json.loads(inp)
            except json.JSONDecodeError:
                parsed = None
        if isinstance(parsed, dict):
            pf = parsed.get("parse_failure")
            if pf not in (None, "", {}, []):
                active_parse_failure = True
                break
            if parsed.get("access_denied") is True:
                denied_route = True

    clarified = clarify_route or active_parse_failure
    denied = denied_route
    full = {"compute_baseline", "run_scenario", "generate_narrative"}.issubset(names)
    # In-flight: parsed OK and moved past parse, but quant/narrative not finished yet.
    in_flight = (
        not full
        and not clarify_route
        and not denied
        and ("check_access" in names or "route_after_access" in names or "compute_baseline" in names)
    )

    overlay_extract = _has_overlay_extract(spans)
    retriever = _has_retriever(spans)
    mcp_tool = _has_mcp_tool(spans)
    # demo.py overlay: search (+ optional) + extract LLM — no LangGraph parse_query.
    overlay_like = ("parse_query" not in names) and (overlay_extract or (retriever and not full))
    tool_like = ("parse_query" not in names) and mcp_tool and not overlay_extract and not full

    if clarify_route and not full:
        path = "guardrail_clarify"
    elif denied and not full:
        path = "access_denied"
    elif full:
        path = "full_success"
    elif in_flight:
        path = "partial"
    elif "parse_query" in names:
        path = "partial"
    elif overlay_like:
        path = "overlay_success"
    elif tool_like:
        path = "mcp_tool"
    else:
        path = "unknown"

    return {
        "path": path,
        "names": sorted(n for n in names if n),
        "clarified": clarified,
        "denied": denied,
        "full": full,
        "clarify_route": clarify_route,
        "active_parse_failure": active_parse_failure,
        "in_flight": in_flight,
        "overlay_extract": overlay_extract,
        "retriever": retriever,
        "mcp_tool": mcp_tool,
    }


def score_latest_run_path(spans: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-run path expectations — this is what should differ across demo commands."""
    info = classify_run_path(spans)
    path = info["path"]
    names = set(info["names"])

    if path == "full_success":
        expected = [
            "parse_query",
            "check_access",
            "compute_baseline",
            "run_scenario",
            "generate_narrative",
        ]
        present = [n for n in expected if n in names]
        passed = len(present) == len(expected)
        score = len(present) / len(expected)
        detail = "happy-path query should reach narrative"
    elif path == "guardrail_clarify":
        routes = [s for s in spans if s.get("name") == "route_after_parse"]
        clarify_ok = any(str(s.get("output_value") or "").strip() == "clarify" for s in routes)
        # Must NOT continue into quant core.
        leaked = bool(names & {"compute_baseline", "run_scenario", "generate_narrative"})
        passed = clarify_ok and not leaked and "parse_query" in names
        score = 1.0 if passed else 0.0
        detail = "out_of_scope/unknown_segment must route to clarify and stop"
        present = sorted(names)
        expected = ["parse_query", "route_after_parse=clarify"]
    elif path == "access_denied":
        leaked = bool(names & {"compute_baseline", "run_scenario", "generate_narrative"})
        passed = "check_access" in names and not leaked
        score = 1.0 if passed else 0.0
        detail = "access denial must stop before quant core"
        present = sorted(names)
        expected = ["parse_query", "check_access", "stop"]
    elif path == "overlay_success":
        # Overlay demos: extract ratings required; retriever optional (bundled sample).
        has_extract = bool(info.get("overlay_extract"))
        has_ret = bool(info.get("retriever"))
        passed = has_extract or has_ret
        score = 1.0 if (has_extract and has_ret) else (0.85 if has_extract else (0.7 if has_ret else 0.0))
        detail = "overlay demo: extract and/or retriever spans (no LangGraph query path)"
        present = sorted(names)
        expected = ["tavily.search|RETRIEVER?", "ChatCompletion(overlay extract)"]
    elif path == "mcp_tool":
        passed = bool(info.get("mcp_tool"))
        score = 1.0 if passed else 0.0
        detail = "MCP tool demo: mcp.call_tool present"
        present = sorted(names)
        expected = ["mcp.call_tool"]
    else:
        # Truly unknown — don't hard-fail empty/noise windows; soft-fail with detail.
        passed = False
        score = 0.0
        detail = (
            f"incomplete/unknown path={path}; "
            "expected query, overlay, mcp_tool, clarify, or access_denied"
        )
        present = sorted(names)
        expected = ["parse_query|overlay|mcp.call_tool"]

    if path == "full_success":
        expected_out = [
            "parse_query",
            "check_access",
            "compute_baseline",
            "run_scenario",
            "generate_narrative",
        ]
        present_out = present
    else:
        expected_out = expected
        present_out = present

    return {
        "passed": passed,
        "score": round(score, 3),
        "path": path,
        "detail": detail,
        "present": present_out,
        "expected": expected_out,
        "classification": info,
    }


def score_latest_run_kinds(spans: list[dict[str, Any]]) -> dict[str, Any]:
    """Kind expectations depend on path (clarify runs may have LLM+CHAIN only)."""
    info = classify_run_path(spans)
    kinds = Counter(s.get("span_kind") or "UNKNOWN" for s in spans)
    path = info["path"]
    if path == "full_success":
        hard = [k for k in ("CHAIN", "LLM") if kinds.get(k, 0) == 0]
    elif path in {"guardrail_clarify", "access_denied", "partial"}:
        hard = [k for k in ("CHAIN",) if kinds.get(k, 0) == 0]
    elif path == "overlay_success":
        # Extract is LLM; live search adds RETRIEVER. Bundled-sample overlay may be LLM-only.
        hard = [k for k in ("LLM",) if kinds.get(k, 0) == 0]
    elif path == "mcp_tool":
        hard = [k for k in ("TOOL",) if kinds.get(k, 0) == 0]
    else:
        hard = []
    passed = not hard
    return {
        "passed": passed,
        "score": 1.0 if passed else 0.0,
        "counts": dict(kinds),
        "hard_missing": hard,
        "path": path,
    }


def run_all_trace_scorers(spans: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    return [
        ("trace_kind_coverage", score_kind_coverage(spans)),
        ("trace_unknown_kind_rate", score_unknown_kind_rate(spans)),
        ("trace_error_rate", score_error_rate(spans)),
        ("trace_graph_nodes", score_graph_node_presence(spans)),
        ("trace_guardrail_clarify", score_guardrail_clarify_traces(spans)),
        ("trace_retriever", score_retriever_traces(spans)),
        ("trace_mcp_tools", score_mcp_tool_traces(spans)),
        ("trace_narrative_caveat", score_narrative_caveat_traces(spans)),
    ]


def run_latest_run_scorers(spans: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """Scorers intended for a single demo run's spans (watch mode)."""
    return [
        ("run_path", score_latest_run_path(spans)),
        ("run_kinds", score_latest_run_kinds(spans)),
        ("run_error_rate", score_error_rate(spans)),
        ("run_guardrail_clarify", score_guardrail_clarify_traces(spans)),
        ("run_narrative_caveat", score_narrative_caveat_traces(spans)),
        ("run_retriever", score_retriever_traces(spans)),
        ("run_mcp_tools", score_mcp_tool_traces(spans)),
    ]
