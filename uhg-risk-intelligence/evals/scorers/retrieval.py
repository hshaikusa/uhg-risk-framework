from __future__ import annotations

import re
from typing import Any

# Lightweight keyword bags — offline proxy for retrieval relevance when no LLM judge.
SEGMENT_KEYWORDS = {
    "Optum_Health": ("optum health", "medicare advantage", "ma ", "care delivery", "care-delivery"),
    "Optum_Insight": ("optum insight", "claims", "cyber", "change healthcare", "health-data", "health data"),
    "Optum_Rx": ("optum rx", "pharmacy", "prescription"),
    "UHC_Medicare_Retirement": ("medicare", "retirement", "uhc"),
    "UHC_Community_State": ("medicaid", "community", "state"),
    "UHC_Employer_Individual": ("employer", "individual", "commercial"),
}

DRIVER_KEYWORDS = {
    "Capital": ("rate", "reimbursement", "margin", "funding", "earnings", "capital"),
    "Demand": ("utilization", "enrollment", "demand", "volume"),
    "Data_Digital": ("cyber", "data", "digital", "security", "claims-processing", "claims processing"),
    "Supply": ("supply", "tariff", "trade", "shortage"),
    "Infrastructure": ("infrastructure", "facility", "network"),
    "Talent": ("talent", "workforce", "staffing"),
    "Brand_Reputation": ("reputation", "brand", "trust"),
}


def score_retrieval_relevance(
    retrieved_text: str,
    *,
    segment: str,
    driver: str,
    expect_relevant: bool,
) -> dict[str, Any]:
    text = retrieved_text.lower()
    seg_hits = [k for k in SEGMENT_KEYWORDS.get(segment, ()) if k in text]
    drv_hits = [k for k in DRIVER_KEYWORDS.get(driver, ()) if k in text]
    # Relevant if at least one segment cue AND one driver cue, or strong driver+healthcare
    healthcare = bool(re.search(r"health|medicare|medicaid|claims|optum|uhc|uhg", text))
    predicted_relevant = bool(seg_hits and drv_hits) or bool(healthcare and drv_hits and len(drv_hits) >= 2)
    passed = predicted_relevant == expect_relevant
    return {
        "passed": passed,
        "score": 1.0 if passed else 0.0,
        "predicted_relevant": predicted_relevant,
        "expect_relevant": expect_relevant,
        "segment_hits": seg_hits,
        "driver_hits": drv_hits,
    }
