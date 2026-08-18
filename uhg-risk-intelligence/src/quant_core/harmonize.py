"""
Layer 2 analog: Harmonization Layer — standardize SCALE.

Two unlike raw scales get transformed onto the same 0-100 axis:
  - cardinal hazard scores -> a log-severity curve, robust-scaled
  - ordinal structural/digital ranks -> a tail-amplified rank percentile

Both transforms are ports of the original framework's design, kept because
the underlying statistical rationale (non-linear severity; compounding
structural deficits) is domain-independent, NOT because the fitted constants
are assumed to transfer. See calibration note below.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# NOTE ON CALIBRATION: SP_LOG_BASE and RANK_TAIL_GAMMA below are inherited
# from the original framework's fitted values. They have NOT been recalibrated
# against CMS rate-notice history or state-ranking history, because that
# history doesn't exist yet for this proof-of-concept. Treat these as
# reasonable *starting* constants, not validated ones.
SP_LOG_BASE = 2.2
RANK_TAIL_GAMMA = 1.15
MOMENTUM_SCALE = 5  # points added/subtracted per +1/-1 outlook


def cardinal_severity_transform(scores: pd.Series, outlooks: pd.Series | None = None) -> pd.Series:
    """Cardinal (e.g. 0.1-10) hazard scores -> 0-100 severity.

    scores: raw cardinal scores, one per country/entity for a single indicator
    outlooks: optional +1/0/-1 momentum signal, same index as scores
    """
    severity = np.power(SP_LOG_BASE, scores)
    p10, p90 = severity.quantile(0.10), severity.quantile(0.90)
    span = max(p90 - p10, 1e-9)  # guard against a degenerate all-equal series
    norm = ((severity - p10) / span * 100).clip(0, 100)
    if outlooks is not None:
        norm = (norm + MOMENTUM_SCALE * outlooks).clip(0, 100)
    return norm


def ordinal_rank_transform(ranks: pd.Series) -> pd.Series:
    """Ordinal ranks (1 = best) -> 0-100 fragility, with weak-tail
    amplification so bottom-quartile entities read disproportionately worse.
    """
    n = len(ranks)
    if n <= 1:
        # Can't compute a meaningful percentile from a single point — this
        # is exactly the low-N situation flagged in weighting.py; harmonize
        # still needs *a* number, so return the midpoint rather than pretend
        # precision that doesn't exist.
        return pd.Series([50.0] * n, index=ranks.index)
    pct = (ranks - 0.5) / n
    return (100 * np.power(pct, RANK_TAIL_GAMMA)).clip(0, 100)
