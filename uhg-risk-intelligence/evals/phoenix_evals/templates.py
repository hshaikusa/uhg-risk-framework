"""Prompt templates for Arize Phoenix ClassificationEvaluator graders.

Aligned with custom judges in evals/judges/ (same rubrics, Phoenix-native API).
"""

from __future__ import annotations

NARRATIVE_FAITHFULNESS_TEMPLATE = """You are a strict factuality judge for UHG risk narratives.
Given a ScenarioOutput (authoritative numbers/pathway) and a narrative text,
decide whether the narrative is faithful to the scenario.

Rules:
- Risk/opportunity/pathway claims must match the scenario (small rounding OK).
- Invented magnitudes, wrong pathway, or recommending action when pathway is null → unfaithful.
- Confidence caveat wording is OUT OF SCOPE (code owns that).
- Prefer factual support over fluency.

Scenario JSON:
{scenario_json}

Narrative:
{narrative_text}

Classify as faithful or unfaithful.
"""

NARRATIVE_STYLE_TEMPLATE = """You judge whether a UHG risk narrative matches its intended audience.

analyst: 2–3 sentences; may include segment/driver/disruptor, numbers, confidence;
  factual tone; methodology-adjacent detail is OK.
executive: ideally ONE sentence; recommended action and why; NO methodology detail;
  NO explicit confidence discussion (caveat may still be appended by code).

Audience: {audience}

Narrative:
{narrative_text}

Classify as appropriate or inappropriate.
"""

RETRIEVAL_RELEVANCE_TEMPLATE = """You judge whether a retrieved news/policy snippet is relevant
to a UHG risk query about a given segment and driver.

relevant=true only if the snippet substantively relates to that segment/driver
risk theme (healthcare finance, cyber, supply, policy, etc. as appropriate).
Generic weather or unrelated market noise → irrelevant.

Query: {query}
Segment: {segment}
Driver: {driver}

Retrieved text:
{retrieved_text}

Classify as relevant or irrelevant.
"""

OVERLAY_CALIBRATION_TEMPLATE = """You are an independent risk rater for healthcare news/policy text.
Given source text plus a proposed overlay rating (sign + 0-3 ordinals), decide
whether the ratings are calibrated (reasonable for UHG/segment/driver context).

Guidelines:
- Prefer conservative severity when uncertain.
- Cyber outages / payment disruption often severity 3, high immediacy.
- Rate-notice / policy updates often severity 2–3, medium immediacy, lasting persistence.
- Mark calibrated only if overall ratings are defensible within ±1 of a reasonable rating.

Segment: {segment}
Driver: {driver}
Proposed rating JSON: {proposed_rating_json}

Source text:
{source_text}

Classify as calibrated or not_calibrated.
"""
