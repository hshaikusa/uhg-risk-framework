"""
Data contracts for the pipeline.

Design rule this file exists to enforce: every boundary between a deterministic
step and an LLM step is a validated Pydantic object, never a free-text string.
If a step can't produce a value that satisfies its schema, it fails closed —
it does not get passed downstream as a best guess.
"""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, confloat, conint


# --------------------------------------------------------------------------
# Layer 1/2 boundary: what a natural-language question gets parsed into
# --------------------------------------------------------------------------

class Segment(str, Enum):
    UHC_MEDICARE_RETIREMENT = "UHC_Medicare_Retirement"
    UHC_COMMUNITY_STATE = "UHC_Community_State"
    UHC_EMPLOYER_INDIVIDUAL = "UHC_Employer_Individual"
    OPTUM_HEALTH = "Optum_Health"
    OPTUM_RX = "Optum_Rx"
    OPTUM_INSIGHT = "Optum_Insight"


class Driver(str, Enum):
    DEMAND = "Demand"
    SUPPLY = "Supply"
    INFRASTRUCTURE = "Infrastructure"
    DATA_DIGITAL = "Data_Digital"
    CAPITAL = "Capital"
    TALENT = "Talent"
    BRAND_REPUTATION = "Brand_Reputation"


class Disruptor(str, Enum):
    D1_TRADE_REWIRING = "D1_trade_rewiring"
    D2_NATIONAL_SECURITY = "D2_national_security_policy"
    D3_TECH_DATA_DIVERGENCE = "D3_tech_data_divergence"
    D4_POWER_BALANCE = "D4_global_power_balance"
    D5_CONFLICT = "D5_conflict"
    D6_POLITICAL_VOLATILITY = "D6_political_regulatory_volatility"


class Pathway(str, Enum):
    """Healthcare-specific response pathways — NOT the original
    Divest/Structured-Decoupling/Double-Down taxonomy, which was built for a
    market-entry decision and doesn't map onto payer economics. See the
    design-decision note in scenario/engine.py.
    """
    EXIT_LOW_MARGIN_MARKETS = "exit_low_margin_markets"
    RENEGOTIATE_RISK_SHARING = "renegotiate_risk_sharing"
    ADJUST_BID_STRATEGY = "adjust_bid_strategy"
    HOLD_CURRENT_POSITION = "hold_current_position"


class ScenarioQuery(BaseModel):
    """Output of the query-parser LLM step. Schema-validated before the
    deterministic core ever sees it — an object that doesn't parse into this
    shape is rejected, not guessed at.
    """
    segment: Segment
    drivers: list[Driver] = Field(min_length=1)
    disruptor: Disruptor
    as_of: Optional[date] = None
    raw_question: str = Field(description="The original NL question, kept for audit trail")


class ParseFailure(BaseModel):
    """Explicit fail-closed result. The graph checks for this type and routes
    to a clarification request instead of guessing a segment.
    """
    reason: Literal["unknown_segment", "unknown_disruptor", "ambiguous", "out_of_scope"]
    raw_question: str
    suggestion: Optional[str] = None


# --------------------------------------------------------------------------
# Quant core outputs (fully deterministic — no LLM touches these fields)
# --------------------------------------------------------------------------

class DriverBaseline(BaseModel):
    segment: Segment
    driver: Driver
    risk_score: confloat(ge=0, le=100)
    opportunity_score: confloat(ge=0, le=100)
    coverage: confloat(ge=0, le=1) = Field(description="Fraction of possible indicators with data")
    confidence: confloat(ge=0, le=1) = Field(description="Coverage weighted by source-quality priors")
    weighting_method: Literal["entropy_critic_hybrid", "expert_elicited_fallback"]
    as_of: date


class ScenarioOutput(BaseModel):
    segment: Segment
    disruptor: Disruptor
    driver: Driver
    final_risk: confloat(ge=0, le=100)
    final_opportunity: confloat(ge=0, le=100)
    recommended_pathway: Optional[Pathway] = Field(
        default=None,
        description="None if confidence floor not met — the system refuses "
                     "to recommend rather than force a low-confidence pick.",
    )
    net_strategic_value: Optional[float] = None
    confidence: confloat(ge=0, le=1)
    below_confidence_floor: bool


# --------------------------------------------------------------------------
# Layer 1/2 boundary: the overlay-extractor's structured output
# --------------------------------------------------------------------------

class OverlaySign(str, Enum):
    RISK = "risk"
    OPPORTUNITY = "opportunity"


class OverlayEvent(BaseModel):
    """The ten-field schema an unstructured news/policy text gets mapped
    into. STAGED by design — see guardrails/gates.py — this object is never
    allowed to touch a live score without a human confirming it first.
    """
    sign: OverlaySign
    severity_0_to_3: conint(ge=0, le=3)
    immediacy_0_to_3: conint(ge=0, le=3)
    persistence_0_to_3: conint(ge=0, le=3)
    sector_relevance_0_to_1: confloat(ge=0, le=1)
    driver_relevance_0_to_1: confloat(ge=0, le=1)
    novelty_residual_0_to_1: confloat(ge=0, le=1) = Field(
        description="Proportion of signal not yet reflected in published quant data"
    )
    confidence_0_to_1: confloat(ge=0, le=1)
    segment: Segment
    driver: Driver
    source_text: str
    source_url: Optional[str] = None
    status: Literal["staged", "confirmed", "rejected"] = "staged"
    extracted_by_model: str
    extracted_at: date


# --------------------------------------------------------------------------
# Output-layer boundary: what the narrative generator receives and returns
# --------------------------------------------------------------------------

class NarrativeAudience(str, Enum):
    ANALYST = "analyst"
    EXECUTIVE = "executive"


class NarrativeOutput(BaseModel):
    audience: NarrativeAudience
    text: str
    confidence_caveat_shown: bool = Field(
        description="Guardrail check: True whenever confidence was below "
                     "threshold and the template forced the caveat in."
    )
    source_scenario: ScenarioOutput
