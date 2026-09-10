from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from evals.suites.offline import run_all_offline
from evals.types import CaseResult, SuiteReport


def _print_report(report: SuiteReport) -> None:
    status = "PASS" if report.passed == report.total else "FAIL"
    print(
        f"[{status}] {report.name}: {report.passed}/{report.total} "
        f"(pass_rate={report.pass_rate:.0%}, mean_score={report.mean_score:.3f})"
    )
    for case in report.results:
        mark = "ok" if case.passed else "X"
        err = f" error={case.error}" if case.error else ""
        print(f"  ({mark}) {case.case_id} score={case.score:.3f}{err}")


def _run_live_safely() -> list[SuiteReport]:
    """Run live suites with progress + suite-level error capture (no silent hang bailout)."""
    from evals.suites import live as live_mod

    reports: list[SuiteReport] = []
    from evals.suites import judge_live as judge_mod

    suite_runners = [
        ("live_query_parser", live_mod.run_live_parser),
        ("live_overlay_double_rate", live_mod.run_live_overlay),
        ("live_narrative_judge", judge_mod.run_live_narrative_judge),
        ("live_narrative_style_judge", judge_mod.run_live_narrative_style_judge),
        ("live_retrieval_judge", judge_mod.run_live_retrieval_judge),
        ("live_overlay_judge", judge_mod.run_live_overlay_judge),
    ]
    for name, fn in suite_runners:
        print(f"\n>> Running {name} (OpenAI calls — may take ~30–90s)...")
        sys.stdout.flush()
        try:
            report = fn()
        except Exception as exc:  # noqa: BLE001
            report = SuiteReport(
                name,
                [
                    CaseResult(
                        suite=name,
                        case_id="_suite_error",
                        passed=False,
                        score=0.0,
                        error=str(exc),
                    )
                ],
            )
            print(f"!! {name} aborted: {exc}")
        _print_report(report)
        reports.append(report)
    return reports


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="UHG Risk Intelligence eval runner (offline by default)."
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Also run LLM-backed suites (requires OPENAI_API_KEY).",
    )
    parser.add_argument(
        "--live-only",
        action="store_true",
        help="Skip offline suites; run only LLM-backed suites.",
    )
    parser.add_argument(
        "--phoenix",
        action="store_true",
        help="Score recent spans from a running Phoenix (trace-based evals).",
    )
    parser.add_argument(
        "--phoenix-only",
        action="store_true",
        help="Skip fixture suites; only score live Phoenix spans.",
    )
    parser.add_argument(
        "--phoenix-limit",
        type=int,
        default=200,
        help="Max spans to pull from Phoenix (default 200).",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Continuously poll Phoenix and re-score when new traces appear.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=15.0,
        help="Seconds between Phoenix polls in --watch mode (default 15).",
    )
    parser.add_argument(
        "--annotate",
        action="store_true",
        help="With --phoenix/--watch, write CODE eval annotations back to Phoenix.",
    )
    parser.add_argument(
        "--judge",
        action="store_true",
        help=(
            "With --watch/--phoenix: also run LLM-as-judge on latest-run narrative/"
            "retrieval/overlay spans (needs OPENAI_API_KEY + JUDGE_MODEL)."
        ),
    )
    parser.add_argument(
        "--phoenix-evals",
        action="store_true",
        help=(
            "Run Arize phoenix.evals ClassificationEvaluators on latest-run spans "
            "(narrative/retrieval/overlay). Implies Phoenix fetch; use with "
            "--annotate to log LLM annotations. Needs OPENAI_API_KEY + JUDGE_MODEL."
        ),
    )
    parser.add_argument(
        "--judges-only",
        action="store_true",
        help="Skip offline + parser/overlay live; run only LLM-as-judge fixture suites.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help=(
            "One-shot full suite: offline + live (parser/overlay/judges) + Phoenix "
            "path evals with LLM judges when Phoenix is reachable. "
            "Does not start --watch (use that separately for continuous demos)."
        ),
    )
    parser.add_argument(
        "--project",
        type=str,
        default=None,
        help="Phoenix project name (default: PHOENIX_PROJECT or uhg-risk-intelligence).",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional path to write a machine-readable report JSON.",
    )
    args = parser.parse_args(argv)
    if args.all:
        # Full one-shot profile. Watch stays opt-in (never exits).
        args.live = True
        args.phoenix = True
        args.judge = True
        args.phoenix_evals = True
        args.live_only = False
        args.judges_only = False
        args.phoenix_only = False
    if args.live_only or args.judges_only:
        args.live = True
    if args.phoenix_only or args.watch or args.phoenix_evals:
        args.phoenix = True
    if args.project:
        os.environ["PHOENIX_PROJECT"] = args.project

    # Ensure project root imports resolve when invoked as python -m evals
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from src.env_loader import load_project_env

    load_project_env()

    if args.watch:
        if args.all:
            print(
                "NOTE: --all ignores --watch. Run without --all for continuous mode:\n"
                "  python -m evals --watch --interval 10 --judge --phoenix-evals --annotate"
            )
        from evals.watch import watch_phoenix

        return watch_phoenix(
            interval_sec=args.interval,
            limit=args.phoenix_limit,
            annotate=bool(args.annotate),
            json_out=args.json_out,
            with_llm_judge=bool(args.judge),
            with_phoenix_evals=bool(args.phoenix_evals),
        )

    reports: list[SuiteReport] = []
    print("=== UHG Risk Intelligence evals ===")
    if args.all:
        print("mode=--all (offline + live + phoenix one-shot with judges)")
    skip_fixtures = bool(args.phoenix_only) or bool(args.judges_only)
    if not args.live_only and not skip_fixtures:
        print("\n>> Offline suites (fixtures + sample Phoenix spans)...")
        sys.stdout.flush()
        for report in run_all_offline():
            _print_report(report)
            reports.append(report)

    if args.judges_only:
        print("\n>> LLM-as-judge suites only...")
        sys.stdout.flush()
        from evals.suites import judge_live as judge_mod

        for name, fn in [
            ("live_narrative_judge", judge_mod.run_live_narrative_judge),
            ("live_narrative_style_judge", judge_mod.run_live_narrative_style_judge),
            ("live_retrieval_judge", judge_mod.run_live_retrieval_judge),
            ("live_overlay_judge", judge_mod.run_live_overlay_judge),
        ]:
            print(f"\n>> Running {name} (JUDGE_MODEL)...")
            sys.stdout.flush()
            try:
                report = fn()
            except Exception as exc:  # noqa: BLE001
                report = SuiteReport(
                    name,
                    [
                        CaseResult(
                            suite=name,
                            case_id="_suite_error",
                            passed=False,
                            score=0.0,
                            error=str(exc),
                        )
                    ],
                )
                print(f"!! {name} aborted: {exc}")
            _print_report(report)
            reports.append(report)
    elif args.live:
        reports.extend(_run_live_safely())

    if args.phoenix:
        print("\n>> Phoenix trace evals (live observability spans)...")
        sys.stdout.flush()
        try:
            from evals.suites.traces import run_trace_evals_phoenix
            from evals.traces import fetch_phoenix_spans
            from evals.watch import _annotate_phoenix

            spans = fetch_phoenix_spans(limit=args.phoenix_limit)
            report = run_trace_evals_phoenix(limit=args.phoenix_limit)
            if args.annotate:
                n = _annotate_phoenix(report, spans)
                print(f"  annotated {n} eval scores onto Phoenix")
            _print_report(report)
            reports.append(report)

            if args.judge:
                from evals.suites.judge_phoenix import run_phoenix_llm_judges
                from evals.traces.summary import latest_run_spans

                print("\n>> Phoenix LLM-as-judge (latest run)...")
                sys.stdout.flush()
                judge_report = run_phoenix_llm_judges(latest_run_spans(spans) or spans)
                if args.annotate:
                    n = _annotate_phoenix(
                        judge_report, spans, annotator_kind="LLM"
                    )
                    print(f"  annotated {n} judge scores onto Phoenix")
                _print_report(judge_report)
                reports.append(judge_report)

            if args.phoenix_evals:
                from evals.suites.phoenix_native import run_phoenix_evals_latest
                from evals.traces.summary import latest_run_spans, newest_span

                print("\n>> Phoenix native evaluators (phoenix.evals)...")
                sys.stdout.flush()
                run_spans = latest_run_spans(spans) or spans
                mirror = newest_span(run_spans) or newest_span(spans)
                for pref in ("LangGraph", "generate_narrative", "parse_query", "tavily.search"):
                    hit = next((s for s in run_spans if s.get("name") == pref), None)
                    if hit:
                        mirror = hit
                        break
                px_report = run_phoenix_evals_latest(
                    limit=args.phoenix_limit,
                    annotate=bool(args.annotate),
                    window_spans=spans,
                    mirror_span_id=str(mirror.get("span_id")) if mirror else None,
                )
                _print_report(px_report)
                reports.append(px_report)
        except Exception as exc:  # noqa: BLE001
            report = SuiteReport(
                "trace_evals_phoenix",
                [
                    CaseResult(
                        suite="trace_evals_phoenix",
                        case_id="_phoenix_error",
                        passed=False,
                        score=0.0,
                        error=str(exc),
                    )
                ],
            )
            print(f"!! Phoenix fetch failed: {exc}")
            _print_report(report)
            reports.append(report)

    # Standalone --phoenix-evals without --phoenix path already covered above
    # when phoenix_evals implies phoenix=True.

    total_pass = sum(r.passed for r in reports)
    total_cases = sum(r.total for r in reports)
    print(f"\nOverall: {total_pass}/{total_cases} cases passed")

    if args.json_out:
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "live": bool(args.live),
            "suites": [
                {
                    "name": r.name,
                    "passed": r.passed,
                    "total": r.total,
                    "pass_rate": r.pass_rate,
                    "mean_score": r.mean_score,
                    "results": [asdict(c) for c in r.results],
                }
                for r in reports
            ],
        }
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Wrote {args.json_out}")

    return 0 if total_pass == total_cases else 1


if __name__ == "__main__":
    raise SystemExit(main())
