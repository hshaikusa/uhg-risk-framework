from __future__ import annotations

from typing import Any

from evals.scorers.traces import run_all_trace_scorers, run_latest_run_scorers
from evals.traces import fetch_phoenix_spans, load_span_fixture
from evals.traces.summary import latest_run_spans, summarize_latest_run
from evals.types import CaseResult, SuiteReport


def _suite_from_scored(
    suite_name: str,
    scored_items: list[tuple[str, dict[str, Any]]],
    *,
    empty_error: str,
) -> SuiteReport:
    if not scored_items:
        return SuiteReport(
            suite_name,
            [
                CaseResult(
                    suite=suite_name,
                    case_id="_no_spans",
                    passed=False,
                    score=0.0,
                    error=empty_error,
                )
            ],
        )
    results = [
        CaseResult(
            suite=suite_name,
            case_id=case_id,
            passed=bool(scored.get("passed")),
            score=float(scored.get("score") or 0.0),
            detail=scored,
        )
        for case_id, scored in scored_items
    ]
    return SuiteReport(suite_name, results)


def _suite_from_spans(suite_name: str, spans: list) -> SuiteReport:
    if not spans:
        return _suite_from_scored(
            suite_name,
            [],
            empty_error="No spans available — start Phoenix and run demo.py, or use the offline fixture.",
        )
    return _suite_from_scored(
        suite_name,
        run_all_trace_scorers(spans),
        empty_error="No spans available.",
    )


def run_trace_evals_offline() -> SuiteReport:
    spans = load_span_fixture("sample_phoenix_spans.json")
    return _suite_from_spans("trace_evals_offline", spans)


def run_trace_evals_phoenix(*, limit: int = 200) -> SuiteReport:
    spans = fetch_phoenix_spans(limit=limit)
    return _suite_from_spans("trace_evals_phoenix", spans)


def spans_for_latest_run(window_spans: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    summary = summarize_latest_run(window_spans)
    run_spans = latest_run_spans(window_spans)
    return run_spans, summary


def run_trace_evals_latest_run(window_spans: list[dict[str, Any]]) -> SuiteReport:
    """Score only the latest demo run — outcomes should differ by command."""
    run_spans, summary = spans_for_latest_run(window_spans)
    if not run_spans:
        return _suite_from_scored(
            "trace_evals_latest_run",
            [],
            empty_error="Could not isolate latest demo run spans.",
        )
    report = _suite_from_scored(
        "trace_evals_latest_run",
        run_latest_run_scorers(run_spans),
        empty_error="Could not isolate latest demo run spans.",
    )
    for case in report.results:
        detail = dict(case.detail or {})
        detail["latest_run"] = summary
        case.detail = detail
    return report
