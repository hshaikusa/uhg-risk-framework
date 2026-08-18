"""
Layer 3 analog: Driver Baseline Layer.

Combines harmonized, weighted indicator scores into one risk score and one
opportunity score per (segment, driver), on the same logistic-scale
combination logic as the original framework (F11/F12), because the
underlying reason for it — keeping the 0-100 range well-behaved and letting
hazard/structural interact non-linearly — doesn't depend on the domain.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from src.quant_core.ontology import INDICATOR_REGISTRY, loading_for
from src.quant_core.weighting import compute_weights
from src.schemas import DriverBaseline, Driver, Segment

# Beta coefficients for the logistic combination. Same role as the original
# framework's F11/F12 betas — governs how much weight the combined indicator
# score carries. Not recalibrated against real outcome data yet (see
# harmonize.py calibration note); reasonable starting values.
BETA_RISK = 0.06
BETA_OPP = 0.06


def _logistic(x: float) -> float:
    return 1 / (1 + np.exp(-x))


def compute_driver_baseline(
    segment: Segment,
    driver: Driver,
    indicator_scores: pd.DataFrame,  # columns: indicator_id, score_0_100, entity (rows = cross-section)
    as_of: date,
) -> DriverBaseline:
    """indicator_scores holds harmonized (0-100) scores for every indicator
    that loads on `driver`, across whatever cross-section is available
    (e.g. peer segments, historical periods) — this is the `matrix` that
    weighting.compute_weights uses to decide entropy/CRITIC vs. fallback.
    """
    relevant_ids = [
        row["indicator_id"] for _, row in INDICATOR_REGISTRY.iterrows()
        if loading_for(row, driver) > 0
    ]
    scored = indicator_scores[indicator_scores["indicator_id"].isin(relevant_ids)]
    if scored.empty:
        raise ValueError(f"No indicator data available for driver {driver} — cannot baseline")

    pivot = scored.pivot_table(index="entity", columns="indicator_id", values="score_0_100")
    weights, method = compute_weights(pivot)

    # Coverage must reflect REAL data for this specific entity, not whether
    # a fallback estimate could be produced. Bug found and fixed live while
    # demoing --sparse-data: an earlier version used `pivot.mean()` both as
    # the point-estimate fallback AND as the source `coverage` was computed
    # from, which meant a segment with ZERO real data for every indicator
    # still reported coverage=1.0 as long as some OTHER segment had data —
    # the mean silently backfilled every "missing" value with a real-looking
    # number. Coverage now comes only from this entity's own real rows;
    # the cross-sectional mean is used strictly as a last-resort point
    # estimate for scoring, kept separate from what coverage measures.
    own_row_real = pivot.loc[segment.value] if segment.value in pivot.index else pd.Series(dtype=float)
    real_available = own_row_real.dropna()
    coverage = len(real_available) / len(relevant_ids)

    fallback_row = pivot.mean()
    combined = own_row_real.combine_first(fallback_row)
    available = combined.dropna()
    w_available = weights.reindex(available.index).fillna(0)
    w_available = w_available / w_available.sum() if w_available.sum() > 0 else w_available

    weighted_score = float((available * w_available).sum())
    risk = _logistic(BETA_RISK * (weighted_score - 50)) * 100
    opportunity = _logistic(BETA_OPP * (50 - weighted_score)) * 100

    source_quality_avg = 0.97  # simplified: see ontology.SOURCE_QUALITY_PRIOR for the real per-layer priors
    confidence = coverage * source_quality_avg

    return DriverBaseline(
        segment=segment,
        driver=driver,
        risk_score=round(risk, 1),
        opportunity_score=round(opportunity, 1),
        coverage=round(coverage, 2),
        confidence=round(confidence, 2),
        weighting_method=method,
        as_of=as_of,
    )
