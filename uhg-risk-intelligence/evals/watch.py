"""Continuous online evals: poll Phoenix as new traces arrive."""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.suites.traces import run_trace_evals_latest_run
from evals.traces import fetch_phoenix_spans
from evals.traces.summary import newest_span, summarize_latest_run
from evals.types import SuiteReport


def _span_ids(spans: list[dict[str, Any]]) -> set[str]:
    return {str(s["span_id"]) for s in spans if s.get("span_id")}


def _annotate_phoenix(
    report: SuiteReport,
    spans: list[dict[str, Any]],
    *,
    annotator_kind: str = "CODE",
) -> int:
    """Write aggregate annotations onto a span from the newest run."""
    if not spans:
        return 0
    try:
        from phoenix.client import Client
    except ImportError as exc:
        print(f"!! cannot annotate (phoenix client missing): {exc}")
        return 0

    base_url = os.getenv("PHOENIX_BASE_URL") or "http://127.0.0.1:6006"
    if base_url.rstrip("/").endswith("/v1/traces"):
        base_url = base_url.rstrip("/")[: -len("/v1/traces")] or "http://127.0.0.1:6006"
    client = Client(base_url=base_url)

    target = newest_span(spans) or spans[0]
    newest_trace = target.get("trace_id")
    if newest_trace:
        preferred = next(
            (
                s
                for s in spans
                if s.get("trace_id") == newest_trace
                and s.get("name")
                in {
                    "LangGraph",
                    "parse_query",
                    "mcp.call_tool",
                    "tavily.search",
                    "generate_narrative",
                    "route_after_parse",
                }
            ),
            target,
        )
        target = preferred

    span_id = target.get("span_id")
    if not span_id:
        return 0

    written = 0
    for case in report.results:
        label = "pass" if case.passed else ("skip" if (case.detail or {}).get("skipped") else "fail")
        try:
            client.spans.add_span_annotation(
                span_id=str(span_id),
                annotation_name=f"eval.{case.case_id}",
                annotator_kind=annotator_kind,
                label=label,
                score=float(case.score),
                explanation=json.dumps(case.detail or {}, default=str)[:1500],
                metadata={
                    "suite": report.name,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                },
                sync=False,
            )
            written += 1
        except Exception as exc:  # noqa: BLE001
            print(f"!! annotate {case.case_id} failed: {exc}")
    return written


def _print_case(case) -> None:
    skipped = bool((case.detail or {}).get("skipped"))
    if skipped:
        mark = "-"
    elif case.passed:
        mark = "ok"
    else:
        mark = "X"
    path = (case.detail or {}).get("path")
    extra = f" path={path}" if path else ""
    skip = " skipped" if skipped else ""
    print(f"  ({mark}) {case.case_id} score={case.score:.3f}{skip}{extra}")


def watch_phoenix(
    *,
    interval_sec: float = 15.0,
    limit: int = 200,
    annotate: bool = False,
    json_out: Path | None = None,
    once_if_empty: bool = False,
    with_llm_judge: bool = False,
    with_phoenix_evals: bool = False,
) -> int:
    """Poll Phoenix forever (Ctrl+C to stop). Re-score each new demo run."""
    project = os.getenv("PHOENIX_PROJECT") or "uhg-risk-intelligence"
    base_url = os.getenv("PHOENIX_BASE_URL") or "http://127.0.0.1:6006"
    print(
        "=== Continuous Phoenix evals (per latest run) ===\n"
        f"project={project!r} · base_url={base_url!r}\n"
        f"polling every {interval_sec:.0f}s · limit={limit} · annotate={annotate} "
        f"· llm_judge={with_llm_judge} · phoenix_evals={with_phoenix_evals}\n"
        "Scores the NEWEST demo run only (not the whole 200-span window).\n"
        "Ctrl+C to stop.\n"
    )
    sys.stdout.flush()

    seen_ids: set[str] = set()
    cycles = 0
    last_exit = 0

    try:
        while True:
            cycles += 1
            ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
            try:
                spans = fetch_phoenix_spans(limit=limit, project=project, base_url=base_url)
            except Exception as exc:  # noqa: BLE001
                print(f"[{ts}] fetch error: {exc}")
                sys.stdout.flush()
                time.sleep(interval_sec)
                continue

            current_ids = _span_ids(spans)
            new_ids = current_ids - seen_ids
            newest = newest_span(spans)
            newest_desc = (
                f"{newest.get('name')} @ {newest.get('start_time')}"
                if newest
                else "none"
            )

            if not current_ids:
                print(f"[{ts}] no spans in project {project!r} — waiting...")
                sys.stdout.flush()
                if once_if_empty and cycles == 1:
                    return 1
                time.sleep(interval_sec)
                continue

            if not new_ids and seen_ids:
                print(
                    f"[{ts}] no new span IDs ({len(current_ids)} in window; "
                    f"newest={newest_desc}) — waiting..."
                )
                sys.stdout.flush()
                time.sleep(interval_sec)
                continue

            from evals.scorers.traces import classify_run_path
            from evals.traces.summary import _as_dt, latest_run_spans

            run_spans_preview = latest_run_spans(spans)
            path_preview = classify_run_path(run_spans_preview).get("path")
            newest_dt = _as_dt(newest.get("start_time")) if newest else None
            age_sec = None
            if newest_dt is not None:
                now = datetime.now(timezone.utc)
                if newest_dt.tzinfo is None:
                    newest_dt = newest_dt.replace(tzinfo=timezone.utc)
                age_sec = (now - newest_dt).total_seconds()
            if path_preview == "partial" and age_sec is not None and age_sec < 12:
                print(
                    f"[{ts}] latest run still partial/in-flight "
                    f"(age={age_sec:.1f}s) — waiting to settle..."
                )
                sys.stdout.flush()
                time.sleep(interval_sec)
                continue

            added = len(new_ids) if seen_ids else len(current_ids)
            seen_ids |= current_ids
            if len(seen_ids) > limit * 20:
                seen_ids = set(current_ids)

            latest_run = summarize_latest_run(spans)
            print(
                f"\n[{ts}] +{added} new span IDs "
                f"(window={len(current_ids)}; newest={newest_desc}) — scoring latest run..."
            )
            if latest_run and latest_run.get("question"):
                print(f"  latest demo question: {latest_run['question']!r}")
                print(
                    f"  latest trace: {latest_run.get('trace_id')} · "
                    f"nodes={', '.join(n for n in (latest_run.get('span_names') or []) if n in {'parse_query','check_access','compute_baseline','run_scenario','generate_narrative','LangGraph','route_after_parse'})}"
                )
            sys.stdout.flush()

            report = run_trace_evals_latest_run(spans)
            path = None
            for case in report.results:
                if case.case_id == "run_path":
                    path = (case.detail or {}).get("path")
            status = "PASS" if report.passed == report.total else "FAIL"
            print(
                f"[{status}] {report.name}: {report.passed}/{report.total} "
                f"(pass_rate={report.pass_rate:.0%}, mean_score={report.mean_score:.3f}"
                f"{f', path={path}' if path else ''})"
            )
            for case in report.results:
                _print_case(case)

            judge_report = None
            if with_llm_judge:
                from evals.suites.judge_phoenix import run_phoenix_llm_judges

                run_spans = latest_run_spans(spans)
                print("  >> LLM-as-judge on latest run...")
                sys.stdout.flush()
                judge_report = run_phoenix_llm_judges(run_spans or spans)
                jstatus = "PASS" if judge_report.passed == judge_report.total else "FAIL"
                print(
                    f"  [{jstatus}] {judge_report.name}: "
                    f"{judge_report.passed}/{judge_report.total} "
                    f"(pass_rate={judge_report.pass_rate:.0%}, "
                    f"mean_score={judge_report.mean_score:.3f})"
                )
                for case in judge_report.results:
                    _print_case(case)

            px_report = None
            annotate_target = newest_span(spans) or {}
            # Prefer a stable demo node for UI visibility
            for pref in (
                "LangGraph",
                "generate_narrative",
                "parse_query",
                "tavily.search",
                "mcp.call_tool",
            ):
                hit = next((s for s in latest_run_spans(spans) if s.get("name") == pref), None)
                if hit:
                    annotate_target = hit
                    break
            target_id = annotate_target.get("span_id")
            target_name = annotate_target.get("name")

            if with_phoenix_evals:
                from evals.suites.phoenix_native import run_phoenix_evals_latest

                print("  >> Phoenix native evaluators (phoenix.evals)...")
                sys.stdout.flush()
                px_report = run_phoenix_evals_latest(
                    limit=limit,
                    annotate=annotate,
                    window_spans=spans,
                    mirror_span_id=str(target_id) if target_id else None,
                )
                pstatus = "PASS" if px_report.passed == px_report.total else "FAIL"
                print(
                    f"  [{pstatus}] {px_report.name}: "
                    f"{px_report.passed}/{px_report.total} "
                    f"(pass_rate={px_report.pass_rate:.0%}, "
                    f"mean_score={px_report.mean_score:.3f})"
                )
                for case in px_report.results:
                    _print_case(case)
                px_ann = 0
                for case in px_report.results:
                    px_ann = max(px_ann, int((case.detail or {}).get("annotations_logged") or 0))
                if annotate:
                    print(f"  phoenix_eval annotations logged: {px_ann}")

            if annotate:
                n = _annotate_phoenix(report, spans)
                print(
                    f"  annotated {n} path scores onto span "
                    f"{target_id} ({target_name})"
                )
                if judge_report is not None:
                    n2 = _annotate_phoenix(judge_report, spans, annotator_kind="LLM")
                    print(f"  annotated {n2} LLM-judge scores")

            if json_out:
                payload = {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "mode": "watch_latest_run",
                    "project": project,
                    "span_count": len(spans),
                    "new_span_ids": added,
                    "newest": {
                        "name": newest.get("name") if newest else None,
                        "start_time": str(newest.get("start_time")) if newest else None,
                        "span_id": newest.get("span_id") if newest else None,
                    },
                    "latest_run": latest_run,
                    "suite": {
                        "name": report.name,
                        "passed": report.passed,
                        "total": report.total,
                        "pass_rate": report.pass_rate,
                        "mean_score": report.mean_score,
                        "results": [asdict(c) for c in report.results],
                    },
                    "llm_judge": (
                        {
                            "name": judge_report.name,
                            "passed": judge_report.passed,
                            "total": judge_report.total,
                            "pass_rate": judge_report.pass_rate,
                            "mean_score": judge_report.mean_score,
                            "results": [asdict(c) for c in judge_report.results],
                        }
                        if judge_report is not None
                        else None
                    ),
                    "phoenix_evals": (
                        {
                            "name": px_report.name,
                            "passed": px_report.passed,
                            "total": px_report.total,
                            "pass_rate": px_report.pass_rate,
                            "mean_score": px_report.mean_score,
                            "results": [asdict(c) for c in px_report.results],
                        }
                        if px_report is not None
                        else None
                    ),
                }
                json_out.parent.mkdir(parents=True, exist_ok=True)
                json_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                print(f"  wrote {json_out}")

            last_exit = 0 if report.passed == report.total else 1
            if judge_report is not None and judge_report.passed != judge_report.total:
                last_exit = 1
            if px_report is not None and px_report.passed != px_report.total:
                last_exit = 1
            sys.stdout.flush()
            time.sleep(interval_sec)
    except KeyboardInterrupt:
        print("\nStopped watch loop.")
        return last_exit
