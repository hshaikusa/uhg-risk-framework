from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from src.quant_core.baseline import compute_driver_baseline
from src.quant_core.ontology import INDICATOR_REGISTRY, loading_for
from src.schemas import Driver, Segment


def _indicator_frame(
    *,
    elevate_segment: str,
    elevate_driver: Driver,
    elevate_score: float = 88.0,
    baseline_score: float = 45.0,
) -> pd.DataFrame:
    """Synthetic cross-section: target segment/driver indicators elevated."""
    entities = [s.value for s in Segment]
    rows: list[dict[str, Any]] = []
    for _, row in INDICATOR_REGISTRY.iterrows():
        ind_id = row["indicator_id"]
        loads = loading_for(row, elevate_driver) > 0
        for entity in entities:
            if loads and entity == elevate_segment:
                score = elevate_score
            elif loads:
                score = baseline_score
            else:
                score = baseline_score
            rows.append(dict(indicator_id=ind_id, entity=entity, score_0_100=score))
    return pd.DataFrame(rows)


def score_anchor_directional(
    *,
    segment: str,
    driver: str,
    min_risk: float = 55.0,
    peer_gap: float = 5.0,
) -> dict[str, Any]:
    """Would an elevated Capital/Data_Digital read show for the anchor segment?

    Uses synthetic-but-directional indicator stress (not live feeds). Passes if
    target risk is above min_risk and above the mean of peer segments by peer_gap.
    """
    seg = Segment(segment)
    drv = Driver(driver)
    scores = _indicator_frame(elevate_segment=segment, elevate_driver=drv)
    as_of = date(2025, 1, 15)

    target = compute_driver_baseline(seg, drv, scores, as_of)
    peer_risks = []
    for other in Segment:
        if other == seg:
            continue
        peer = compute_driver_baseline(other, drv, scores, as_of)
        peer_risks.append(peer.risk_score)
    peer_mean = float(np.mean(peer_risks)) if peer_risks else 0.0
    elevated = target.risk_score >= min_risk and (target.risk_score - peer_mean) >= peer_gap
    return {
        "passed": elevated,
        "score": 1.0 if elevated else round(min(1.0, target.risk_score / 100.0), 3),
        "target_risk": target.risk_score,
        "peer_mean_risk": round(peer_mean, 1),
        "risk_gap": round(target.risk_score - peer_mean, 1),
        "min_risk": min_risk,
        "peer_gap": peer_gap,
        "confidence": target.confidence,
        "coverage": target.coverage,
    }
