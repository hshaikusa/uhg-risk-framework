from __future__ import annotations

from typing import Any

from src.guardrails.gates import (
    GuardrailRejection,
    question_in_uhg_scope,
    validate_query,
)
from src.schemas import Driver, Disruptor, ScenarioQuery, Segment


def score_scope_marker(question: str, expect_in_scope: bool) -> dict[str, Any]:
    actual = question_in_uhg_scope(question)
    passed = actual == expect_in_scope
    return {
        "passed": passed,
        "score": 1.0 if passed else 0.0,
        "actual_in_scope": actual,
        "expect_in_scope": expect_in_scope,
    }


def score_validate_query(
    question: str,
    *,
    segment: str,
    expect_reject_reason: str | None,
    drivers: list[str] | None = None,
    disruptor: str = "D6_political_regulatory_volatility",
) -> dict[str, Any]:
    query = ScenarioQuery(
        segment=Segment(segment),
        drivers=[Driver(d) for d in (drivers or ["Capital"])],
        disruptor=Disruptor(disruptor),
        raw_question=question,
    )
    try:
        validate_query(query)
        rejected = False
        reason = None
    except GuardrailRejection as exc:
        rejected = True
        reason = exc.reason

    if expect_reject_reason is None:
        passed = not rejected
    else:
        passed = rejected and reason == expect_reject_reason

    return {
        "passed": passed,
        "score": 1.0 if passed else 0.0,
        "rejected": rejected,
        "reason": reason,
        "expect_reject_reason": expect_reject_reason,
    }
