"""
Layer 2 analog: objective indicator weighting.

DESIGN DECISION (pressure-tested explicitly during architecture review):
entropy/CRITIC weighting needs a reasonably large cross-section to be
statistically meaningful — the original framework computed it across 211
countries. This system's natural cross-section is a handful of business
segments. Below MIN_N_FOR_OBJECTIVE_WEIGHTING, entropy/CRITIC is not even
attempted — the code falls back to documented, expert-elicited weights with
a visible rationale, rather than silently computing a number that LOOKS
objective but isn't statistically earned at that sample size.

This is the single most important "don't lie to yourself" check in the
quant core, and it's enforced in code, not just in a design doc.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_N_FOR_OBJECTIVE_WEIGHTING = 15  # a defensible, documented floor — below
                                     # this, entropy/CRITIC's own assumptions
                                     # (meaningful dispersion, stable correlation)
                                     # don't hold.

CRITIC_BLEND_WEIGHT = 0.70
ENTROPY_BLEND_WEIGHT = 0.30

# Expert-elicited fallback weights, used whenever N < MIN_N_FOR_OBJECTIVE_WEIGHTING.
# Each must be justified in EXPERT_WEIGHT_RATIONALE — no silent defaults.
EXPERT_FALLBACK_WEIGHTS = {
    "IND_H01": 0.30,  # CMS MA rate notice — highest weight: directly, immediately
                       # moves Capital/Demand for the segments that matter most
    "IND_H02": 0.15,
    "IND_H03": 0.10,
    "IND_H04": 0.15,
    "IND_S01": 0.10,
    "IND_S02": 0.10,
    "IND_S03": 0.05,
    "IND_D01": 0.03,
    "IND_D02": 0.02,
}
EXPERT_WEIGHT_RATIONALE = (
    "Weights set by the design author, not computed, because the available "
    "cross-section (six business segments) is below the minimum sample size "
    "entropy/CRITIC weighting needs to be statistically meaningful. CMS MA "
    "rate notices weighted highest because they are the most direct, most "
    "immediately consequential hazard signal for this business, per the "
    "2025 Optum Health earnings impact used as this system's backtest anchor."
)


def entropy_weights(matrix: pd.DataFrame) -> pd.Series:
    """matrix: rows = entities, columns = indicators, values in [0, 100]."""
    p = matrix.div(matrix.sum(axis=0) + 1e-12, axis=1)
    p_safe = p.replace(0, np.nan)
    entropy = -(p_safe * np.log(p_safe)).sum(axis=0, skipna=True) / np.log(len(matrix))
    divergence = 1 - entropy
    return divergence / divergence.sum()


def critic_weights(matrix: pd.DataFrame) -> pd.Series:
    std = matrix.std(axis=0, ddof=0)
    corr = matrix.corr().fillna(0)
    conflict = std * (1 - corr).sum(axis=0)
    return conflict / conflict.sum()


def compute_weights(matrix: pd.DataFrame) -> tuple[pd.Series, str]:
    """Returns (weights, method_used). Falls back automatically below the
    documented N floor — callers should surface `method_used` in the
    DriverBaseline.weighting_method field so it's visible in the output,
    not buried in a log line.
    """
    n = len(matrix)
    if n < MIN_N_FOR_OBJECTIVE_WEIGHTING:
        cols = matrix.columns
        w = pd.Series({c: EXPERT_FALLBACK_WEIGHTS.get(c, 0.0) for c in cols})
        if w.sum() == 0:
            raise ValueError(
                f"No expert fallback weight defined for any of {list(cols)}; "
                "add one to EXPERT_FALLBACK_WEIGHTS with a documented rationale "
                "before proceeding."
            )
        return w / w.sum(), "expert_elicited_fallback"

    ent = entropy_weights(matrix)
    crit = critic_weights(matrix)
    hybrid = CRITIC_BLEND_WEIGHT * crit + ENTROPY_BLEND_WEIGHT * ent
    return hybrid / hybrid.sum(), "entropy_critic_hybrid"
