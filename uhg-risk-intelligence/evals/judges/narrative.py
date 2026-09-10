"""LLM judges for narrative faithfulness and audience style."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from evals.judges.client import MIN_JUDGE_SCORE, judge_structured
from src.schemas import NarrativeAudience, ScenarioOutput

FAITHFULNESS_SYSTEM = """You are a strict factuality judge for UHG risk narratives.
Given a ScenarioOutput (authoritative numbers/pathway) and a narrative text,
decide whether the narrative is faithful to the scenario.

Rules:
- Risk/opportunity/pathway claims must match the scenario (small rounding OK).
- Invented magnitudes, wrong pathway, or recommending action when pathway is null → unfaithful.
- Confidence caveat wording is OUT OF SCOPE (code owns that).
- Prefer factual support over fluency; list concrete unsupported claims.
- score is overall faithfulness in [0,1].
"""

STYLE_SYSTEM = """You judge whether a UHG risk narrative matches its intended audience.

analyst: 2–3 sentences; may include segment/driver/disruptor, numbers, confidence;
  factual tone; methodology-adjacent detail is OK.
executive: ideally ONE sentence; recommended action and why; NO methodology detail;
  NO explicit confidence discussion (caveat may still be appended by code).

Flag style_issues for mismatches (e.g. executive essay with methodology,
analyst missing key numbers when they were available).
score is audience-fit quality in [0,1].
"""


class NarrativeFaithfulnessVerdict(BaseModel):
    faithful: bool
    unsupported_claims: list[str] = Field(default_factory=list)
    risk_numbers_ok: bool
    pathway_ok: bool
    score: float = Field(ge=0.0, le=1.0)
    rationale: str


class NarrativeStyleVerdict(BaseModel):
    audience_appropriate: bool
    style_issues: list[str] = Field(default_factory=list)
    score: float = Field(ge=0.0, le=1.0)
    rationale: str


def _scenario_payload(scenario: ScenarioOutput | dict[str, Any]) -> dict[str, Any]:
    if isinstance(scenario, ScenarioOutput):
        return scenario.model_dump(mode="json")
    return dict(scenario)


def judge_narrative_faithfulness(
    scenario: ScenarioOutput | dict[str, Any],
    narrative_text: str,
) -> NarrativeFaithfulnessVerdict:
    payload = {
        "scenario": _scenario_payload(scenario),
        "narrative_text": narrative_text,
    }
    return judge_structured(
        system=FAITHFULNESS_SYSTEM,
        user=json.dumps(payload, indent=2),
        response_model=NarrativeFaithfulnessVerdict,
    )


def judge_narrative_style(
    narrative_text: str,
    audience: str | NarrativeAudience,
) -> NarrativeStyleVerdict:
    aud = audience.value if isinstance(audience, NarrativeAudience) else str(audience)
    payload = {"audience": aud, "narrative_text": narrative_text}
    return judge_structured(
        system=STYLE_SYSTEM,
        user=json.dumps(payload, indent=2),
        response_model=NarrativeStyleVerdict,
    )


def score_narrative_faithfulness_verdict(
    verdict: NarrativeFaithfulnessVerdict | dict[str, Any],
    *,
    expect_faithful: bool | None = None,
    min_score: float = MIN_JUDGE_SCORE,
) -> dict[str, Any]:
    if isinstance(verdict, NarrativeFaithfulnessVerdict):
        data = verdict.model_dump()
    else:
        data = dict(verdict)

    faithful = bool(data.get("faithful"))
    score = float(data.get("score") or 0.0)
    risk_ok = bool(data.get("risk_numbers_ok"))
    pathway_ok = bool(data.get("pathway_ok"))
    pass_rule = faithful and score >= min_score and risk_ok and pathway_ok

    label_agree: bool | None = None
    if expect_faithful is not None:
        label_agree = faithful == bool(expect_faithful)
        if expect_faithful:
            # Good narrative: judge must pass bar AND agree with label.
            passed = pass_rule and label_agree
        else:
            # Bad fixture: judge must also mark unfaithful (score bar N/A).
            passed = label_agree and (not faithful)
    else:
        passed = pass_rule

    return {
        "passed": passed,
        "score": round(score, 3),
        "pass_rule": pass_rule,
        "label_agree": label_agree,
        "expect_faithful": expect_faithful,
        "min_score": min_score,
        "verdict": data,
    }


def score_narrative_style_verdict(
    verdict: NarrativeStyleVerdict | dict[str, Any],
    *,
    expect_appropriate: bool | None = None,
    min_score: float = MIN_JUDGE_SCORE,
) -> dict[str, Any]:
    if isinstance(verdict, NarrativeStyleVerdict):
        data = verdict.model_dump()
    else:
        data = dict(verdict)

    appropriate = bool(data.get("audience_appropriate"))
    score = float(data.get("score") or 0.0)
    pass_rule = appropriate and score >= min_score

    label_agree: bool | None = None
    if expect_appropriate is not None:
        label_agree = appropriate == bool(expect_appropriate)
        if expect_appropriate is False:
            passed = label_agree and (not appropriate)
        else:
            passed = pass_rule and label_agree
    else:
        passed = pass_rule

    return {
        "passed": passed,
        "score": round(score, 3),
        "pass_rule": pass_rule,
        "label_agree": label_agree,
        "expect_appropriate": expect_appropriate,
        "min_score": min_score,
        "verdict": data,
    }
