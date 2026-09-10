"""Live LLM-as-judge suites (JUDGE_MODEL)."""

from __future__ import annotations

import os
from typing import Any

from evals.fixtures_io import load_jsonl
from evals.judges.narrative import (
    judge_narrative_faithfulness,
    judge_narrative_style,
    score_narrative_faithfulness_verdict,
    score_narrative_style_verdict,
)
from evals.judges.overlay import judge_overlay_calibration, score_overlay_judge_verdict
from evals.judges.retrieval import judge_retrieval_relevance, score_retrieval_judge_verdict
from evals.types import CaseResult, SuiteReport
from src.schemas import Driver, NarrativeAudience, ScenarioOutput, Segment


def _require_api_key() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("Live judge evals require OPENAI_API_KEY in the environment")


def _scenario(row_scenario: dict[str, Any]) -> ScenarioOutput:
    return ScenarioOutput(**row_scenario)


def _resolve_narrative_text(row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Return narrative text and meta (generated or fixture)."""
    mode = row.get("mode", "fixture")
    audience = NarrativeAudience(row.get("audience", "analyst"))
    scenario = _scenario(row["scenario"])
    meta: dict[str, Any] = {"mode": mode, "audience": audience.value}

    if mode == "generate":
        from src.ai_steps.narrative_generator import generate_narrative

        out = generate_narrative(scenario, audience)
        meta["generated"] = True
        meta["confidence_caveat_shown"] = out.confidence_caveat_shown
        return out.text, meta

    text = row.get("narrative_text")
    if not text:
        raise ValueError(f"{row.get('id')}: fixture mode requires narrative_text")
    meta["generated"] = False
    return str(text), meta


def run_live_narrative_judge() -> SuiteReport:
    _require_api_key()
    results: list[CaseResult] = []
    for row in load_jsonl("narrative_judge.jsonl"):
        try:
            text, meta = _resolve_narrative_text(row)
            verdict = judge_narrative_faithfulness(row["scenario"], text)
            scored = score_narrative_faithfulness_verdict(
                verdict, expect_faithful=row.get("expect_faithful")
            )
            results.append(
                CaseResult(
                    suite="live_narrative_judge",
                    case_id=row["id"],
                    passed=bool(scored["passed"]),
                    score=float(scored["score"]),
                    detail={**scored, **meta, "narrative_text": text},
                )
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                CaseResult(
                    suite="live_narrative_judge",
                    case_id=row["id"],
                    passed=False,
                    score=0.0,
                    error=str(exc),
                )
            )
    return SuiteReport("live_narrative_judge", results)


def run_live_narrative_style_judge() -> SuiteReport:
    _require_api_key()
    results: list[CaseResult] = []
    for row in load_jsonl("narrative_style_judge.jsonl"):
        try:
            text, meta = _resolve_narrative_text(row)
            verdict = judge_narrative_style(text, row.get("audience", "analyst"))
            scored = score_narrative_style_verdict(
                verdict, expect_appropriate=row.get("expect_appropriate")
            )
            results.append(
                CaseResult(
                    suite="live_narrative_style_judge",
                    case_id=row["id"],
                    passed=bool(scored["passed"]),
                    score=float(scored["score"]),
                    detail={**scored, **meta, "narrative_text": text},
                )
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                CaseResult(
                    suite="live_narrative_style_judge",
                    case_id=row["id"],
                    passed=False,
                    score=0.0,
                    error=str(exc),
                )
            )
    return SuiteReport("live_narrative_style_judge", results)


def run_live_retrieval_judge() -> SuiteReport:
    _require_api_key()
    results: list[CaseResult] = []
    for row in load_jsonl("retrieval_relevance.jsonl"):
        try:
            verdict = judge_retrieval_relevance(
                retrieved_text=row["retrieved_text"],
                segment=row["segment"],
                driver=row["driver"],
                query=row.get("query"),
            )
            scored = score_retrieval_judge_verdict(
                verdict, expect_relevant=row.get("expect_relevant")
            )
            results.append(
                CaseResult(
                    suite="live_retrieval_judge",
                    case_id=row["id"],
                    passed=bool(scored["passed"]),
                    score=float(scored["score"]),
                    detail=scored,
                )
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                CaseResult(
                    suite="live_retrieval_judge",
                    case_id=row["id"],
                    passed=False,
                    score=0.0,
                    error=str(exc),
                )
            )
    return SuiteReport("live_retrieval_judge", results)


def run_live_overlay_judge() -> SuiteReport:
    """Judge live overlay extraction calibration (alongside double-rater suite)."""
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
            verdict = judge_overlay_calibration(
                source_text=row["source_text"],
                segment=row["segment"],
                driver=row["driver"],
                predicted=predicted,
            )
            scored = score_overlay_judge_verdict(verdict)
            results.append(
                CaseResult(
                    suite="live_overlay_judge",
                    case_id=row["id"],
                    passed=bool(scored["passed"]),
                    score=float(scored["score"]),
                    detail={**scored, "predicted": predicted, "status": event.status},
                )
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                CaseResult(
                    suite="live_overlay_judge",
                    case_id=row["id"],
                    passed=False,
                    score=0.0,
                    error=str(exc),
                )
            )
    return SuiteReport("live_overlay_judge", results)


def run_all_live_judges() -> list[SuiteReport]:
    return [
        run_live_narrative_judge(),
        run_live_narrative_style_judge(),
        run_live_retrieval_judge(),
        run_live_overlay_judge(),
    ]
