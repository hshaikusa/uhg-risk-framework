"""LLM judge for overlay severity/immediacy/persistence calibration.

Complements (does not replace) double-rater ±1 band scoring.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, confloat, conint

from evals.judges.client import MIN_JUDGE_SCORE, judge_structured

OVERLAY_SYSTEM = """You are an independent risk rater for healthcare news/policy text.
Given source text plus a proposed overlay rating (sign + 0-3 ordinals), decide
whether the ratings are calibrated (reasonable for UHG/segment/driver context).

Guidelines:
- Prefer conservative severity when uncertain.
- Cyber outages / payment disruption often severity 3, high immediacy.
- Rate-notice / policy updates often severity 2–3, medium immediacy, lasting persistence.
- severity_ok / immediacy_ok / persistence_ok: true if proposed value is within ±1
  of what you would assign.
- Also provide your own suggested severity_0_to_3.
- calibrated=true only if overall ratings are defensible.
- score in [0,1] for calibration quality.
"""


class OverlayJudgeVerdict(BaseModel):
    calibrated: bool
    severity_ok: bool
    immediacy_ok: bool
    persistence_ok: bool
    suggested_severity_0_to_3: conint(ge=0, le=3)
    score: confloat(ge=0.0, le=1.0)
    rationale: str
    issues: list[str] = Field(default_factory=list)


def judge_overlay_calibration(
    *,
    source_text: str,
    segment: str,
    driver: str,
    predicted: dict[str, Any],
) -> OverlayJudgeVerdict:
    payload = {
        "segment": segment,
        "driver": driver,
        "source_text": source_text,
        "proposed_rating": {
            "sign": predicted.get("sign"),
            "severity_0_to_3": predicted.get("severity_0_to_3"),
            "immediacy_0_to_3": predicted.get("immediacy_0_to_3"),
            "persistence_0_to_3": predicted.get("persistence_0_to_3"),
        },
    }
    return judge_structured(
        system=OVERLAY_SYSTEM,
        user=json.dumps(payload, indent=2),
        response_model=OverlayJudgeVerdict,
    )


def score_overlay_judge_verdict(
    verdict: OverlayJudgeVerdict | dict[str, Any],
    *,
    min_score: float = MIN_JUDGE_SCORE,
) -> dict[str, Any]:
    if isinstance(verdict, OverlayJudgeVerdict):
        data = verdict.model_dump()
    else:
        data = dict(verdict)

    score = float(data.get("score") or 0.0)
    calibrated = bool(data.get("calibrated"))
    fields_ok = all(
        bool(data.get(k))
        for k in ("severity_ok", "immediacy_ok", "persistence_ok")
    )
    passed = calibrated and fields_ok and score >= min_score
    return {
        "passed": passed,
        "score": round(score, 3),
        "min_score": min_score,
        "verdict": data,
    }
