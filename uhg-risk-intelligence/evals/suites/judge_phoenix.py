"""Phoenix-span LLM-as-judge suite (phase 2 for --watch --judge)."""

from __future__ import annotations

import os
from typing import Any

from evals.judges.narrative import (
    judge_narrative_faithfulness,
    judge_narrative_style,
    score_narrative_faithfulness_verdict,
    score_narrative_style_verdict,
)
from evals.judges.overlay import judge_overlay_calibration, score_overlay_judge_verdict
from evals.judges.phoenix_extract import (
    extract_narrative_from_spans,
    extract_overlay_from_spans,
    extract_retrieval_from_spans,
)
from evals.judges.retrieval import judge_retrieval_relevance, score_retrieval_judge_verdict
from evals.types import CaseResult, SuiteReport


def _skip(suite: str, case_id: str, reason: str) -> CaseResult:
    return CaseResult(
        suite=suite,
        case_id=case_id,
        passed=True,
        score=1.0,
        detail={"skipped": True, "reason": reason},
    )


def run_phoenix_llm_judges(spans: list[dict[str, Any]]) -> SuiteReport:
    """Judge narrative / retrieval / overlay content found in a span window or latest run."""
    suite = "trace_llm_judges"
    if not os.environ.get("OPENAI_API_KEY"):
        return SuiteReport(
            suite,
            [
                CaseResult(
                    suite=suite,
                    case_id="_missing_api_key",
                    passed=False,
                    score=0.0,
                    error="OPENAI_API_KEY required for --judge",
                )
            ],
        )

    results: list[CaseResult] = []

    # --- Narrative faithfulness + style ---
    narr = extract_narrative_from_spans(spans)
    if not narr:
        results.append(_skip(suite, "judge_narrative_faithfulness", "no narrative payload in spans"))
        results.append(_skip(suite, "judge_narrative_style", "no narrative payload in spans"))
    else:
        try:
            faith = judge_narrative_faithfulness(narr["scenario"], narr["narrative_text"])
            scored_f = score_narrative_faithfulness_verdict(faith)
            results.append(
                CaseResult(
                    suite=suite,
                    case_id="judge_narrative_faithfulness",
                    passed=bool(scored_f["passed"]),
                    score=float(scored_f["score"]),
                    detail={**scored_f, "audience": narr.get("audience")},
                )
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                CaseResult(
                    suite=suite,
                    case_id="judge_narrative_faithfulness",
                    passed=False,
                    score=0.0,
                    error=str(exc),
                )
            )
        try:
            style = judge_narrative_style(narr["narrative_text"], narr.get("audience", "analyst"))
            scored_s = score_narrative_style_verdict(style)
            results.append(
                CaseResult(
                    suite=suite,
                    case_id="judge_narrative_style",
                    passed=bool(scored_s["passed"]),
                    score=float(scored_s["score"]),
                    detail={**scored_s, "audience": narr.get("audience")},
                )
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                CaseResult(
                    suite=suite,
                    case_id="judge_narrative_style",
                    passed=False,
                    score=0.0,
                    error=str(exc),
                )
            )

    # --- Retrieval ---
    ret = extract_retrieval_from_spans(spans)
    if not ret:
        results.append(_skip(suite, "judge_retrieval_relevance", "no RETRIEVER spans"))
    else:
        try:
            verdict = judge_retrieval_relevance(
                retrieved_text=ret["retrieved_text"],
                segment=ret["segment"],
                driver=ret["driver"],
                query=ret.get("query"),
            )
            # Online: expect retrieved docs to be relevant to the search.
            scored = score_retrieval_judge_verdict(verdict, expect_relevant=True)
            results.append(
                CaseResult(
                    suite=suite,
                    case_id="judge_retrieval_relevance",
                    passed=bool(scored["passed"]),
                    score=float(scored["score"]),
                    detail={**scored, "segment": ret["segment"], "driver": ret["driver"]},
                )
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                CaseResult(
                    suite=suite,
                    case_id="judge_retrieval_relevance",
                    passed=False,
                    score=0.0,
                    error=str(exc),
                )
            )

    # --- Overlay ---
    overlay = extract_overlay_from_spans(spans)
    if not overlay:
        results.append(_skip(suite, "judge_overlay_calibration", "no overlay extract spans"))
    else:
        try:
            verdict = judge_overlay_calibration(
                source_text=overlay["source_text"],
                segment=overlay["segment"],
                driver=overlay["driver"],
                predicted=overlay["predicted"],
            )
            scored = score_overlay_judge_verdict(verdict)
            results.append(
                CaseResult(
                    suite=suite,
                    case_id="judge_overlay_calibration",
                    passed=bool(scored["passed"]),
                    score=float(scored["score"]),
                    detail={**scored, "predicted": overlay["predicted"]},
                )
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                CaseResult(
                    suite=suite,
                    case_id="judge_overlay_calibration",
                    passed=False,
                    score=0.0,
                    error=str(exc),
                )
            )

    return SuiteReport(suite, results)
