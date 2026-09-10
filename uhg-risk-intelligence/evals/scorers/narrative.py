from __future__ import annotations

import re
from typing import Any

from src.guardrails.gates import CONFIDENCE_FLOOR
from src.schemas import ScenarioOutput

# Keep in sync with src.ai_steps.narrative_generator.LOW_CONFIDENCE_CAVEAT
CAVEAT_MARKER = "below the system's threshold"


def _scenario_from_dict(data: dict[str, Any]) -> ScenarioOutput:
    return ScenarioOutput(**data)


def score_caveat(
    scenario: ScenarioOutput | dict[str, Any],
    narrative_text: str,
    caveat_flag: bool | None = None,
) -> dict[str, Any]:
    if isinstance(scenario, dict):
        scenario = _scenario_from_dict(scenario)
    needs = scenario.confidence < CONFIDENCE_FLOOR or scenario.below_confidence_floor
    text_has = CAVEAT_MARKER in narrative_text
    if caveat_flag is None:
        flag_ok = True
    elif needs:
        flag_ok = caveat_flag is True
    else:
        flag_ok = caveat_flag is False
    passed = (needs == text_has) and flag_ok
    return {
        "passed": passed,
        "score": 1.0 if passed else 0.0,
        "needs_caveat": needs,
        "text_has_caveat": text_has,
        "caveat_flag": caveat_flag,
    }


def score_faithfulness(
    scenario: ScenarioOutput | dict[str, Any],
    narrative_text: str,
) -> dict[str, Any]:
    """Heuristic faithfulness: key numeric outputs should appear; inventing
    a very different risk figure fails. Pathway must not contradict None.
    """
    if isinstance(scenario, dict):
        scenario = _scenario_from_dict(scenario)

    text = narrative_text
    risk_str = str(scenario.final_risk)
    opp_str = str(scenario.final_opportunity)
    has_risk = risk_str in text or risk_str.split(".")[0] in text
    has_opp = opp_str in text

    invented = False
    for match in re.findall(r"\b(\d{2,3}(?:\.\d+)?)\b", text):
        val = float(match)
        if 0 <= val <= 100 and abs(val - scenario.final_risk) >= 15 and abs(val - scenario.final_opportunity) >= 15:
            if val >= 10:
                invented = True
                break

    pathway_ok = True
    if scenario.recommended_pathway is None:
        pathway_ok = not any(
            p in text.lower()
            for p in (
                "exit_low_margin_markets",
                "renegotiate_risk_sharing",
                "adjust_bid_strategy",
                "hold_current_position",
                "exit markets",
            )
        )
    else:
        pathway_ok = (
            scenario.recommended_pathway.value in text
            or scenario.recommended_pathway.value.replace("_", " ") in text.lower()
        )

    score = 0.0
    if has_risk:
        score += 0.45
    if has_opp:
        score += 0.25
    if pathway_ok:
        score += 0.30
    if invented:
        score = min(score, 0.2)

    passed = (not invented) and (has_risk or has_opp) and pathway_ok
    return {
        "passed": passed,
        "score": round(score, 3),
        "has_risk_number": has_risk,
        "has_opportunity_number": has_opp,
        "pathway_ok": pathway_ok,
        "invented_distant_score": invented,
    }
