from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evals.fixtures_io import load_jsonl
from evals.scorers.backtest import score_anchor_directional
from evals.scorers.narrative import score_caveat, score_faithfulness
from evals.scorers.overlay import score_overlay_against_double_raters
from evals.scorers.parser import score_parser_prediction
from evals.scorers.retrieval import score_retrieval_relevance
from evals.scorers.scope import score_scope_marker, score_validate_query
from evals.types import CaseResult, SuiteReport
from src.schemas import ScenarioOutput


def run_scope_gate() -> SuiteReport:
    results: list[CaseResult] = []
    for row in load_jsonl("scope_gate.jsonl"):
        marker = score_scope_marker(row["question"], row["expect_in_scope"])
        detail: dict[str, Any] = {"scope_marker": marker}
        passed = marker["passed"]
        score = marker["score"]

        reject = row.get("expect_reject_reason")
        if reject is not None or row.get("segment_for_validate"):
            segment = row.get("segment_for_validate") or "Optum_Health"
            val = score_validate_query(
                row["question"],
                segment=segment,
                expect_reject_reason=reject,
            )
            detail["validate_query"] = val
            passed = passed and val["passed"]
            score = (score + val["score"]) / 2
        elif not row["expect_in_scope"]:
            # Out-of-scope questions should also fail validate_query when forced through.
            val = score_validate_query(
                row["question"],
                segment="Optum_Health",
                expect_reject_reason="out_of_scope",
            )
            detail["validate_query"] = val
            passed = passed and val["passed"]
            score = (score + val["score"]) / 2

        results.append(
            CaseResult(
                suite="scope_gate",
                case_id=row["id"],
                passed=passed,
                score=score,
                detail=detail,
            )
        )
    return SuiteReport("scope_gate", results)


def run_parser_scorer_smoke() -> SuiteReport:
    """Offline: verify scorer grades perfect / imperfect predictions correctly."""
    results: list[CaseResult] = []
    for row in load_jsonl("query_parser.jsonl"):
        perfect = score_parser_prediction(row["expected"], row["expected"])
        wrong = dict(row["expected"])
        wrong["segment"] = (
            "Optum_Rx" if row["expected"]["segment"] != "Optum_Rx" else "Optum_Health"
        )
        imperfect = score_parser_prediction(wrong, row["expected"])
        passed = perfect["exact"] is True and imperfect["exact"] is False
        results.append(
            CaseResult(
                suite="parser_scorer_smoke",
                case_id=row["id"],
                passed=passed,
                score=1.0 if passed else 0.0,
                detail={"perfect": perfect, "imperfect": imperfect},
            )
        )
    return SuiteReport("parser_scorer_smoke", results)


def run_overlay_calibration_with_rater_mean() -> SuiteReport:
    """Offline: treat mean(rater_a, rater_b) rounded as a pseudo-model prediction."""
    results: list[CaseResult] = []
    for row in load_jsonl("overlay_double_rate.jsonl"):
        a, b = row["rater_a"], row["rater_b"]
        pseudo = {
            "sign": a["sign"] if a["sign"] == b["sign"] else a["sign"],
            "severity_0_to_3": int(round((a["severity_0_to_3"] + b["severity_0_to_3"]) / 2)),
            "immediacy_0_to_3": int(round((a["immediacy_0_to_3"] + b["immediacy_0_to_3"]) / 2)),
            "persistence_0_to_3": int(round((a["persistence_0_to_3"] + b["persistence_0_to_3"]) / 2)),
        }
        scored = score_overlay_against_double_raters(pseudo, a, b)
        results.append(
            CaseResult(
                suite="overlay_double_rate_offline",
                case_id=row["id"],
                passed=scored["passed"],
                score=scored["score"],
                detail=scored,
            )
        )
    return SuiteReport("overlay_double_rate_offline", results)


def run_narrative_faithfulness() -> SuiteReport:
    results: list[CaseResult] = []
    for row in load_jsonl("narrative_faithfulness.jsonl"):
        caveat = score_caveat(row["scenario"], row["narrative_text"])
        faith = score_faithfulness(row["scenario"], row["narrative_text"])
        expect_caveat = row["expect_caveat"]
        expect_faithful = row["expect_faithful"]
        caveat_ok = caveat["needs_caveat"] == expect_caveat and (
            caveat["text_has_caveat"] == expect_caveat
        )
        faith_ok = faith["passed"] == expect_faithful
        passed = caveat_ok and faith_ok
        results.append(
            CaseResult(
                suite="narrative_faithfulness",
                case_id=row["id"],
                passed=passed,
                score=(caveat["score"] + faith["score"]) / 2 if passed else 0.0,
                detail={"caveat": caveat, "faithfulness": faith, "caveat_ok": caveat_ok, "faith_ok": faith_ok},
            )
        )
    return SuiteReport("narrative_faithfulness", results)


def run_narrative_caveat_guardrail() -> SuiteReport:
    """Applies the same post-LLM caveat rule as narrative_generator (no API)."""
    from src.guardrails.gates import CONFIDENCE_FLOOR

    caveat = (
        " Confidence in this figure is currently below the system's threshold "
        "for a fully reliable read — treat this as directional, not final."
    )
    results: list[CaseResult] = []
    cases = [
        ("low_confidence", 0.3, True, True),
        ("high_confidence", 0.85, False, False),
    ]
    for case_id, conf, below, expect_caveat in cases:
        scenario = ScenarioOutput(
            segment="Optum_Health",
            disruptor="D6_political_regulatory_volatility",
            driver="Capital",
            final_risk=72.0,
            final_opportunity=20.0,
            recommended_pathway=None if below else "hold_current_position",
            net_strategic_value=None if below else -5.0,
            confidence=conf,
            below_confidence_floor=below,
        )
        text = "Optum Health shows elevated capital risk under this scenario."
        caveat_shown = False
        if scenario.confidence < CONFIDENCE_FLOOR or scenario.below_confidence_floor:
            text = text.rstrip(". ") + "." + caveat
            caveat_shown = True
        scored = score_caveat(scenario, text, caveat_flag=caveat_shown)
        passed = scored["passed"] and (caveat_shown is expect_caveat)
        results.append(
            CaseResult(
                suite="narrative_caveat_guardrail",
                case_id=case_id,
                passed=passed,
                score=1.0 if passed else 0.0,
                detail={"scored": scored, "text": text},
            )
        )
    return SuiteReport("narrative_caveat_guardrail", results)


def run_retrieval_relevance() -> SuiteReport:
    results: list[CaseResult] = []
    for row in load_jsonl("retrieval_relevance.jsonl"):
        scored = score_retrieval_relevance(
            row["retrieved_text"],
            segment=row["segment"],
            driver=row["driver"],
            expect_relevant=row["expect_relevant"],
        )
        results.append(
            CaseResult(
                suite="retrieval_relevance",
                case_id=row["id"],
                passed=scored["passed"],
                score=scored["score"],
                detail=scored,
            )
        )
    return SuiteReport("retrieval_relevance", results)


def run_backtest_anchors() -> SuiteReport:
    anchors_path = (
        Path(__file__).resolve().parents[2] / "src" / "data" / "backtest_anchors.json"
    )
    anchors = json.loads(anchors_path.read_text(encoding="utf-8"))["anchors"]
    results: list[CaseResult] = []
    for anchor in anchors:
        scored = score_anchor_directional(
            segment=anchor["segment"],
            driver=anchor["driver"],
        )
        results.append(
            CaseResult(
                suite="backtest_anchors",
                case_id=anchor["id"],
                passed=scored["passed"],
                score=scored["score"],
                detail={**scored, "description": anchor["description"]},
            )
        )
    return SuiteReport("backtest_anchors", results)


def run_all_offline() -> list[SuiteReport]:
    from evals.suites.traces import run_trace_evals_offline

    return [
        run_scope_gate(),
        run_parser_scorer_smoke(),
        run_overlay_calibration_with_rater_mean(),
        run_narrative_faithfulness(),
        run_narrative_caveat_guardrail(),
        run_retrieval_relevance(),
        run_backtest_anchors(),
        run_trace_evals_offline(),
    ]
