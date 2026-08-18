"""
Layer 3 analog: the guardrail gate, plus the Layer 4 access-control gate.

Three jobs, each a real function a caller must go through — not a design
note that trusts every caller to remember the rule:
  1. schema validation on parsed queries (enforced by Pydantic at the type
     level already — see schemas.py — this module adds the semantic checks
     Pydantic types alone can't express, e.g. "is this segment retired" or
     "is this question about UHG risk exposure at all")
  2. staging overlay events pending human confirmation
  3. the confidence floor below which no pathway recommendation is produced

Access control is kept separate from the eval/guardrail gate on purpose:
one is about whether the NUMBER is trustworthy, the other is about who's
ALLOWED to see it. Conflating them would make it harder to reason about
either one.
"""
from __future__ import annotations

from src.schemas import OverlayEvent, ScenarioQuery, Segment

# Confidence floor: a defended, tunable parameter with a conservative
# default. If asked "why this number," the honest answer is that it's a
# documented tradeoff (favor refusing a recommendation over surfacing a
# shaky one), not a law of nature.
CONFIDENCE_FLOOR = 0.5

# Segments that no longer exist (e.g. divested units). The query parser can
# still hallucinate a plausible-sounding one; this is the semantic check
# that catches it even if the LLM's output otherwise validates against the
# Segment enum by matching a real (but wrong) member. Human-readable forms
# included since this matches against free-text questions, not enum values.
RETIRED_SEGMENT_ALIASES = {
    "Optum_International", "Optum International",
    "UHG_South_America", "UHG South America",
    "Optum_Global", "Optum Global",
}

# Substrings that indicate the question belongs to this system's domain
# (UHG / Optum / UHC segment and disruptor exposure). The query parser can
# force-fit arbitrary text into the ScenarioQuery schema; this deterministic
# check rejects off-topic input before the quant core runs.
UHG_SCOPE_MARKERS = (
    "optum", "uhc", "uhg", "unitedhealth", "united health",
    "medicare", "medicaid", "medicare advantage", "ma rate",
    "change healthcare", "community and state", "employer and individual",
)


class GuardrailRejection(Exception):
    def __init__(self, reason: str, detail: str):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}")


def question_in_uhg_scope(raw_question: str) -> bool:
    q = raw_question.lower()
    return any(marker in q for marker in UHG_SCOPE_MARKERS)


def validate_query(query: ScenarioQuery) -> ScenarioQuery:
    """Semantic validation beyond what the Pydantic type already enforces.
    Raises GuardrailRejection (never silently substitutes a nearest match)
    so the graph can route to a clarification request.
    """
    if query.raw_question and any(alias.lower() in query.raw_question.lower()
                                   for alias in RETIRED_SEGMENT_ALIASES):
        raise GuardrailRejection(
            "unknown_segment",
            "Question references a segment that no longer exists in the "
            "current portfolio. Ask which current segment they mean instead "
            "of matching to the nearest real one.",
        )
    if query.raw_question and not question_in_uhg_scope(query.raw_question):
        raise GuardrailRejection(
            "out_of_scope",
            "This system answers UnitedHealth Group / Optum / UHC segment "
            "exposure questions only. Rephrase with a current segment "
            "(e.g. Optum Health, Optum Insight) and a disruptor or driver.",
        )
    return query


def stage_overlay_event(event: OverlayEvent) -> OverlayEvent:
    """Every overlay event enters here with status='staged' regardless of
    what the extractor set — this function is the single point where status
    is authoritative, so a bug in the extractor step can't accidentally
    ship a live event.
    """
    event.status = "staged"
    return event


def confirm_overlay_event(event: OverlayEvent, confirmed_by: str) -> OverlayEvent:
    """The only path from staged -> confirmed. Requires an explicit human
    identifier — there is no code path that self-confirms an event.
    """
    if event.status != "staged":
        raise GuardrailRejection("invalid_transition", f"Cannot confirm an event with status={event.status}")
    event.status = "confirmed"
    return event


# --------------------------------------------------------------------------
# Access control gate (Layer 4)
# --------------------------------------------------------------------------

class Role:
    ANALYST = "analyst"
    EXECUTIVE = "executive"
    ADMIN = "admin"
    GUEST = "guest"


# Which roles may view which segments' scenario output. Deliberately
# conservative default (analyst/executive scoped to their own segment list;
# admin sees all) — a real deployment would back this with an actual
# identity/entitlements system, not a static dict, but the GATE ITSELF
# belongs here regardless of what backs it.
SEGMENT_ACCESS = {
    Role.ADMIN: set(Segment),
    Role.EXECUTIVE: set(Segment),
    Role.ANALYST: set(Segment),  # demo default: open; tighten per real org chart
    Role.GUEST: {Segment.OPTUM_RX},  # deliberately narrow — the real demo
                                      # path for the access-control gate,
                                      # not just a unit-test fixture
}


def check_access(role: str, segment: Segment) -> bool:
    allowed = SEGMENT_ACCESS.get(role, set())
    return segment in allowed


def enforce_access(role: str, segment: Segment) -> None:
    if not check_access(role, segment):
        raise GuardrailRejection(
            "access_denied",
            f"Role '{role}' is not permitted to view segment '{segment.value}'",
        )
