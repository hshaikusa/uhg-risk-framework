"""
Layer 4 analog: Scenario Engine.

DESIGN DECISION (pressure-tested explicitly): the original framework's three
response pathways — Divest, Structured Decoupling, Double Down — were built
for a market-entry decision (leave a country, ring-fence a region, expand
into one). A health payer doesn't divest from Medicare Advantage overnight.
The real levers are exiting specific low-margin counties, renegotiating
provider risk-sharing terms, or adjusting next-cycle bid strategy — see
Pathway in schemas.py. This module implements THAT taxonomy, not a relabeled
copy of the original.
"""
from __future__ import annotations

from src.guardrails.gates import CONFIDENCE_FLOOR
from src.schemas import DriverBaseline, Disruptor, Pathway, ScenarioOutput

# Disruptor -> driver risk/opportunity weighting. Only D3 and D6 are given
# non-trivial weight for this business, per the explicit re-weighting
# decision made when adapting the framework from Stellantis to UHG — D1
# matters at the margins (pharma tariffs), D2/D4/D5 are near-zero for a
# domestic payer.
DISRUPTOR_DRIVER_WEIGHT = {
    Disruptor.D1_TRADE_REWIRING: 0.15,
    Disruptor.D2_NATIONAL_SECURITY: 0.05,
    Disruptor.D3_TECH_DATA_DIVERGENCE: 0.85,
    Disruptor.D4_POWER_BALANCE: 0.05,
    Disruptor.D5_CONFLICT: 0.05,
    Disruptor.D6_POLITICAL_VOLATILITY: 0.95,
}

PATHWAY_TRANSITION_COST = {
    Pathway.EXIT_LOW_MARGIN_MARKETS: 15.0,
    Pathway.RENEGOTIATE_RISK_SHARING: 8.0,
    Pathway.ADJUST_BID_STRATEGY: 3.0,
    Pathway.HOLD_CURRENT_POSITION: 0.0,
}

RISK_AVERSION_DEFAULT = 1.0


def _pick_pathway(final_risk: float, final_opportunity: float) -> tuple[Pathway, float]:
    """Simple, explainable pathway selection: net value = opportunity -
    risk_aversion * risk - transition_cost, same structure as the original
    framework's F16, evaluated across the healthcare-specific pathway set.
    """
    best_pathway, best_value = None, float("-inf")
    for pathway, cost in PATHWAY_TRANSITION_COST.items():
        # Illustrative multipliers: holding costs nothing but captures the
        # full risk; exiting/renegotiating/adjusting bid strategy trade
        # transition cost for partial risk reduction. These are starting
        # values, not calibrated against realized outcomes yet.
        risk_mult = {"exit_low_margin_markets": 0.55, "renegotiate_risk_sharing": 0.75,
                     "adjust_bid_strategy": 0.85, "hold_current_position": 1.0}[pathway.value]
        opp_mult = {"exit_low_margin_markets": 0.6, "renegotiate_risk_sharing": 0.9,
                    "adjust_bid_strategy": 0.95, "hold_current_position": 1.0}[pathway.value]
        value = (final_opportunity * opp_mult) - RISK_AVERSION_DEFAULT * (final_risk * risk_mult) - cost
        if value > best_value:
            best_pathway, best_value = pathway, value
    return best_pathway, best_value


def run_scenario(baseline: DriverBaseline, disruptor: Disruptor) -> ScenarioOutput:
    weight = DISRUPTOR_DRIVER_WEIGHT[disruptor]
    final_risk = min(100.0, baseline.risk_score * (1 + weight))
    final_opportunity = max(0.0, baseline.opportunity_score * (1 - weight * 0.5))

    below_floor = baseline.confidence < CONFIDENCE_FLOOR
    if below_floor:
        # Guardrail enforced here, not just documented: the engine itself
        # refuses to name a pathway when confidence is too low, rather than
        # relying on a downstream layer to remember to check.
        return ScenarioOutput(
            segment=baseline.segment, disruptor=disruptor, driver=baseline.driver,
            final_risk=round(final_risk, 1), final_opportunity=round(final_opportunity, 1),
            recommended_pathway=None, net_strategic_value=None,
            confidence=baseline.confidence, below_confidence_floor=True,
        )

    pathway, net_value = _pick_pathway(final_risk, final_opportunity)
    return ScenarioOutput(
        segment=baseline.segment, disruptor=disruptor, driver=baseline.driver,
        final_risk=round(final_risk, 1), final_opportunity=round(final_opportunity, 1),
        recommended_pathway=pathway, net_strategic_value=round(net_value, 1),
        confidence=baseline.confidence, below_confidence_floor=False,
    )
