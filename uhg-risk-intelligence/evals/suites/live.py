from __future__ import annotations

import os
from typing import Any

from evals.fixtures_io import load_jsonl
from evals.scorers.overlay import score_overlay_against_double_raters
from evals.scorers.parser import score_parser_prediction
from evals.types import CaseResult, SuiteReport
from src.schemas import Driver, ParseFailure, Segment


def _require_api_key() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("Live evals require OPENAI_API_KEY in the environment")


def run_live_parser() -> SuiteReport:
    _require_api_key()
    from src.ai_steps.query_parser import parse_query

    results: list[CaseResult] = []
    for row in load_jsonl("query_parser.jsonl"):
        try:
            predicted = parse_query(row["question"])
            if isinstance(predicted, ParseFailure):
                results.append(
                    CaseResult(
                        suite="live_query_parser",
                        case_id=row["id"],
                        passed=False,
                        score=0.0,
                        detail={"parse_failure": predicted.model_dump()},
                        error=predicted.reason,
                    )
                )
                continue
            scored = score_parser_prediction(
                predicted, row["expected"], min_driver_jaccard=0.5
            )
            results.append(
                CaseResult(
                    suite="live_query_parser",
                    case_id=row["id"],
                    passed=bool(scored["passed"]),
                    score=float(scored["score"]),
                    detail=scored,
                )
            )
        except Exception as exc:  # noqa: BLE001 — surface per-case for the report
            results.append(
                CaseResult(
                    suite="live_query_parser",
                    case_id=row["id"],
                    passed=False,
                    score=0.0,
                    error=str(exc),
                )
            )
    return SuiteReport("live_query_parser", results)


def run_live_overlay() -> SuiteReport:
    _require_api_key()
    from src.ai_steps.overlay_extractor import extract_overlay_event

    results: list[CaseResult] = []
    for row in load_jsonl("overlay_double_rate.jsonl"):
        try:
            event = extract_overlay_event(
                source_text=row["source_text"],
                segment=Segment(row["segment"]),
                driver=Driver(row["driver"]),
            )
            predicted: dict[str, Any] = {
                "sign": event.sign.value,
                "severity_0_to_3": event.severity_0_to_3,
                "immediacy_0_to_3": event.immediacy_0_to_3,
                "persistence_0_to_3": event.persistence_0_to_3,
            }
            scored = score_overlay_against_double_raters(
                predicted, row["rater_a"], row["rater_b"]
            )
            results.append(
                CaseResult(
                    suite="live_overlay_double_rate",
                    case_id=row["id"],
                    passed=bool(scored["passed"]),
                    score=float(scored["score"]),
                    detail={**scored, "predicted": predicted, "status": event.status},
                )
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                CaseResult(
                    suite="live_overlay_double_rate",
                    case_id=row["id"],
                    passed=False,
                    score=0.0,
                    error=str(exc),
                )
            )
    return SuiteReport("live_overlay_double_rate", results)


def run_all_live() -> list[SuiteReport]:
    from evals.suites.judge_live import run_all_live_judges

    return [run_live_parser(), run_live_overlay(), *run_all_live_judges()]
