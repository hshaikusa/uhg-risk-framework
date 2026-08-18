"""
Layer 1-2: overlay extractor.

Turns unstructured text (a policy notice, an incident disclosure, a news
article) into the ten-field OverlayEvent schema. Uses the STRONGER model
tier deliberately — see README "Model tiers" — because rating severity,
immediacy, and persistence on a 0-3 scale is a genuine judgment call, not a
mechanical extraction, and two human analysts would plausibly disagree by
+/-1 point. That's also why this is evaluated against double-rated ground
truth in evals/ rather than a single label.

Every event this produces is staged, never live, by the time it leaves this
module — see guardrails.gates.stage_overlay_event, which is called
unconditionally regardless of what the model outputs.
"""
from __future__ import annotations

import os
from datetime import date

import instructor
from pydantic import BaseModel, confloat, conint

from src.guardrails.gates import stage_overlay_event
from src.schemas import Driver, OverlayEvent, OverlaySign, Segment
from src.observability import make_openai_client

STRONG_MODEL = os.environ.get("STRONG_MODEL", "gpt-4o")

SYSTEM_PROMPT = """You read a piece of text describing a real-world event \
(a regulatory notice, an incident disclosure, a news article) relevant to \
UnitedHealth Group and extract it into a structured risk/opportunity \
overlay event. Rate severity, immediacy, and persistence conservatively — \
when uncertain, prefer a lower score over an inflated one, since this \
output will be reviewed by a human analyst before it can affect any live \
score. Set novelty_residual high if the event is very recent and unlikely \
to be reflected in existing published structural or hazard data yet."""


class _OverlayExtractFields(BaseModel):
    """Judgment fields only — metadata (segment, dates, status) is set in
    code after the LLM call. Using the full OverlayEvent as response_model
    breaks OpenInference instructor tracing: its span serializer calls
    json.dumps(resp.dict()) and Python date objects are not JSON-safe.
    """
    sign: OverlaySign
    severity_0_to_3: conint(ge=0, le=3)
    immediacy_0_to_3: conint(ge=0, le=3)
    persistence_0_to_3: conint(ge=0, le=3)
    sector_relevance_0_to_1: confloat(ge=0, le=1)
    driver_relevance_0_to_1: confloat(ge=0, le=1)
    novelty_residual_0_to_1: confloat(ge=0, le=1)
    confidence_0_to_1: confloat(ge=0, le=1)


def get_client() -> instructor.Instructor:
    return instructor.from_openai(make_openai_client())


def extract_overlay_event(
    source_text: str,
    segment: Segment,
    driver: Driver,
    source_url: str | None = None,
) -> OverlayEvent:
    client = get_client()
    extracted: _OverlayExtractFields = client.chat.completions.create(
        model=STRONG_MODEL,
        response_model=_OverlayExtractFields,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"Segment: {segment.value}\nDriver: {driver.value}\n\n"
                f"Text:\n{source_text}"
            )},
        ],
    )
    event = OverlayEvent(
        **extracted.model_dump(),
        segment=segment,
        driver=driver,
        source_text=source_text,
        source_url=source_url,
        extracted_by_model=STRONG_MODEL,
        extracted_at=date.today(),
    )
    return stage_overlay_event(event)  # unconditional — see module docstring
