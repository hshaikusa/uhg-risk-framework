from datetime import date

from src.guardrails.gates import (
    CONFIDENCE_FLOOR, GuardrailRejection, Role, confirm_overlay_event,
    enforce_access, stage_overlay_event, validate_query,
)
from src.scenario.engine import run_scenario
from src.schemas import (
    Disruptor, Driver, DriverBaseline, OverlayEvent, OverlaySign, ScenarioQuery, Segment,
)


def _baseline(confidence: float, risk: float = 60.0, opp: float = 40.0) -> DriverBaseline:
    return DriverBaseline(
        segment=Segment.OPTUM_HEALTH, driver=Driver.CAPITAL,
        risk_score=risk, opportunity_score=opp, coverage=confidence,
        confidence=confidence, weighting_method="expert_elicited_fallback",
        as_of=date(2026, 1, 1),
    )


def test_scenario_recommends_a_pathway_when_confidence_is_healthy():
    out = run_scenario(_baseline(confidence=0.8), Disruptor.D6_POLITICAL_VOLATILITY)
    assert out.below_confidence_floor is False
    assert out.recommended_pathway is not None
    assert out.net_strategic_value is not None


def test_scenario_refuses_pathway_below_confidence_floor():
    low_conf = CONFIDENCE_FLOOR - 0.05
    out = run_scenario(_baseline(confidence=low_conf), Disruptor.D6_POLITICAL_VOLATILITY)
    assert out.below_confidence_floor is True
    assert out.recommended_pathway is None
    assert out.net_strategic_value is None


def test_d6_and_d3_dominate_over_trade_and_conflict_disruptors():
    """The explicit re-weighting decision made when adapting the framework:
    D6/D3 should move the score far more than D1/D2/D4/D5 for this business.
    """
    base = _baseline(confidence=0.9, risk=50.0)
    out_d6 = run_scenario(base, Disruptor.D6_POLITICAL_VOLATILITY)
    out_d5 = run_scenario(base, Disruptor.D5_CONFLICT)
    assert out_d6.final_risk > out_d5.final_risk


def test_query_validation_rejects_out_of_scope_question():
    q = ScenarioQuery(
        segment=Segment.OPTUM_HEALTH,
        drivers=[Driver.DEMAND],
        disruptor=Disruptor.D3_TECH_DATA_DIVERGENCE,
        raw_question="How is NVIDIA stock doing this year?",
    )
    try:
        validate_query(q)
        assert False, "expected GuardrailRejection"
    except GuardrailRejection as e:
        assert e.reason == "out_of_scope"


def test_query_validation_accepts_in_scope_uhg_question():
    q = ScenarioQuery(
        segment=Segment.OPTUM_HEALTH,
        drivers=[Driver.CAPITAL],
        disruptor=Disruptor.D6_POLITICAL_VOLATILITY,
        raw_question="How exposed is Optum Health to a Medicare Advantage rate cut?",
    )
    assert validate_query(q).segment == Segment.OPTUM_HEALTH


def test_query_validation_rejects_retired_segment_reference():
    q = ScenarioQuery(
        segment=Segment.OPTUM_HEALTH,  # LLM would have to pick *some* real
                                        # enum member; the semantic check
                                        # catches the retired-segment mention
                                        # in the raw question regardless
        drivers=[Driver.CAPITAL], disruptor=Disruptor.D6_POLITICAL_VOLATILITY,
        raw_question="How exposed is Optum International to currency risk?",
    )
    try:
        validate_query(q)
        assert False, "expected GuardrailRejection"
    except GuardrailRejection as e:
        assert e.reason == "unknown_segment"


def test_overlay_event_lifecycle_requires_explicit_confirmation():
    event = OverlayEvent(
        sign=OverlaySign.RISK, severity_0_to_3=3, immediacy_0_to_3=3, persistence_0_to_3=2,
        sector_relevance_0_to_1=0.9, driver_relevance_0_to_1=0.9, novelty_residual_0_to_1=0.7,
        confidence_0_to_1=0.85, segment=Segment.OPTUM_INSIGHT, driver=Driver.DATA_DIGITAL,
        source_text="Sample incident disclosure text.", extracted_by_model="gpt-4o",
        extracted_at=date(2026, 1, 1), status="confirmed",  # extractor tries to set this directly
    )
    staged = stage_overlay_event(event)
    assert staged.status == "staged", "stage_overlay_event must override extractor-set status"

    confirmed = confirm_overlay_event(staged, confirmed_by="analyst_jdoe")
    assert confirmed.status == "confirmed"


def test_cannot_confirm_an_event_twice():
    event = OverlayEvent(
        sign=OverlaySign.RISK, severity_0_to_3=2, immediacy_0_to_3=2, persistence_0_to_3=1,
        sector_relevance_0_to_1=0.5, driver_relevance_0_to_1=0.5, novelty_residual_0_to_1=0.5,
        confidence_0_to_1=0.5, segment=Segment.OPTUM_INSIGHT, driver=Driver.DATA_DIGITAL,
        source_text="x", extracted_by_model="gpt-4o", extracted_at=date(2026, 1, 1),
    )
    staged = stage_overlay_event(event)
    confirm_overlay_event(staged, confirmed_by="analyst_jdoe")
    try:
        confirm_overlay_event(staged, confirmed_by="analyst_jdoe")
        assert False, "expected GuardrailRejection on double confirmation"
    except GuardrailRejection as e:
        assert e.reason == "invalid_transition"


def test_access_control_gate_blocks_disallowed_role():
    # ANALYST is open in this demo config; flip it to prove the gate itself works
    from src.guardrails import gates
    gates.SEGMENT_ACCESS[Role.ANALYST] = {Segment.OPTUM_RX}  # scope down for this test
    try:
        enforce_access(Role.ANALYST, Segment.OPTUM_RX)  # allowed, should not raise
        raised = False
        try:
            enforce_access(Role.ANALYST, Segment.OPTUM_INSIGHT)  # not in scope
        except GuardrailRejection as e:
            raised = True
            assert e.reason == "access_denied"
        assert raised, "expected GuardrailRejection for out-of-scope segment"
    finally:
        gates.SEGMENT_ACCESS[Role.ANALYST] = set(Segment)  # restore demo default
