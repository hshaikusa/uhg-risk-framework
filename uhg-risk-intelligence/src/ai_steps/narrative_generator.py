"""
Layer 1-2: narrative generator.

Turns a ScenarioOutput into plain-language text for one of two audiences.
Uses the small/fast model tier, same reasoning as query_parser.py — this is
a templating/rewriting task, not a judgment call, so a cheap model is
appropriate and caching (see README "Optimization") is effective here.

GUARDRAIL ENFORCED IN CODE, not left to the prompt: whenever confidence is
below CONFIDENCE_FLOOR, the caveat sentence is appended AFTER the model
call, deterministically, regardless of what the model wrote. This is the
direct fix for the "false confidence" failure mode named in the pressure
test — a model that drops an inconvenient caveat because the sentence reads
better without it cannot actually remove it, because the code adds it back.
"""
from __future__ import annotations

import os

import instructor
from openai import OpenAI
from pydantic import BaseModel

from src.guardrails.gates import CONFIDENCE_FLOOR
from src.schemas import NarrativeAudience, NarrativeOutput, ScenarioOutput
from src.observability import make_openai_client

FAST_MODEL = os.environ.get("FAST_MODEL", "gpt-4o-mini")

LOW_CONFIDENCE_CAVEAT = (
    " Confidence in this figure is currently below the system's threshold "
    "for a fully reliable read — treat this as directional, not final."
)


class _RawNarrative(BaseModel):
    text: str


def get_client() -> instructor.Instructor:
    return instructor.from_openai(make_openai_client())


def _prompt_for(audience: NarrativeAudience, scenario: ScenarioOutput) -> str:
    if audience == NarrativeAudience.ANALYST:
        return (
            f"Segment: {scenario.segment.value}\nDriver: {scenario.driver.value}\n"
            f"Disruptor: {scenario.disruptor.value}\nFinal risk: {scenario.final_risk}\n"
            f"Final opportunity: {scenario.final_opportunity}\nConfidence: {scenario.confidence}\n"
            f"Recommended pathway: {scenario.recommended_pathway}\n\n"
            "Write a 2-3 sentence analyst-facing summary including the driver "
            "detail and confidence level. Do not editorialize about confidence — "
            "just report it factually; a caveat will be added separately if needed."
        )
    return (
        f"Final risk: {scenario.final_risk}\nFinal opportunity: {scenario.final_opportunity}\n"
        f"Recommended pathway: {scenario.recommended_pathway}\n\n"
        "Write ONE sentence for an executive: the recommended action and why, "
        "no methodology detail, no explicit confidence discussion — a caveat "
        "will be added separately if needed."
    )


def generate_narrative(scenario: ScenarioOutput, audience: NarrativeAudience) -> NarrativeOutput:
    client = get_client()
    raw: _RawNarrative = client.chat.completions.create(
        model=FAST_MODEL,
        response_model=_RawNarrative,
        messages=[{"role": "user", "content": _prompt_for(audience, scenario)}],
    )

    text = raw.text
    caveat_shown = False
    if scenario.confidence < CONFIDENCE_FLOOR or scenario.below_confidence_floor:
        text = text.rstrip(". ") + "." + LOW_CONFIDENCE_CAVEAT
        caveat_shown = True

    return NarrativeOutput(
        audience=audience, text=text,
        confidence_caveat_shown=caveat_shown, source_scenario=scenario,
    )
