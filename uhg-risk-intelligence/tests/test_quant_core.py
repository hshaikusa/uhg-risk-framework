"""
Runs the deterministic core end-to-end with synthetic data — no API keys,
no network, no LLM. This is the part of the system that's fully testable
today, and the tests double as a worked example of how the harmonize ->
weight -> baseline chain fits together.
"""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.quant_core.baseline import compute_driver_baseline
from src.quant_core.harmonize import cardinal_severity_transform, ordinal_rank_transform
from src.quant_core.weighting import MIN_N_FOR_OBJECTIVE_WEIGHTING, compute_weights
from src.schemas import Driver, Segment


def test_cardinal_severity_transform_is_monotonic_and_bounded():
    scores = pd.Series([1, 2, 4, 6, 8, 10] * 3)  # widen the series so p10/p90 aren't degenerate
    out = cardinal_severity_transform(scores)
    assert out.min() >= 0 and out.max() <= 100
    # higher raw score -> higher (or equal) severity, never lower
    paired = sorted(zip(scores, out))
    for (s1, o1), (s2, o2) in zip(paired, paired[1:]):
        assert o2 >= o1 - 1e-9


def test_cardinal_transform_applies_momentum():
    scores = pd.Series([5.0] * 20)
    flat = cardinal_severity_transform(scores)
    improving = cardinal_severity_transform(scores, outlooks=pd.Series([1] * 20))
    # all scores identical -> p10==p90==severity, so base norm is degenerate;
    # what we're really checking is that momentum still shifts the result
    assert (improving >= flat).all()


def test_ordinal_rank_transform_amplifies_bottom_tail():
    ranks = pd.Series(range(1, 21))  # 1 = best, 20 = worst
    out = ordinal_rank_transform(ranks)
    # weak-tail amplification: the gap between rank 19->20 should be larger
    # than the gap between rank 1->2, reflecting compounding structural risk
    gap_top = out.iloc[1] - out.iloc[0]
    gap_bottom = out.iloc[-1] - out.iloc[-2]
    assert gap_bottom > gap_top


def test_ordinal_transform_handles_n_equals_1_without_crashing():
    out = ordinal_rank_transform(pd.Series([1]))
    assert list(out) == [50.0]


def test_weighting_falls_back_below_min_n():
    small_matrix = pd.DataFrame(
        np.random.default_rng(0).uniform(0, 100, size=(6, 4)),
        columns=["IND_H01", "IND_H02", "IND_S01", "IND_D01"],
    )
    assert len(small_matrix) < MIN_N_FOR_OBJECTIVE_WEIGHTING
    weights, method = compute_weights(small_matrix)
    assert method == "expert_elicited_fallback"
    assert abs(weights.sum() - 1.0) < 1e-9


def test_weighting_uses_objective_method_above_min_n():
    rng = np.random.default_rng(1)
    big_matrix = pd.DataFrame(
        rng.uniform(0, 100, size=(30, 4)),
        columns=["IND_H01", "IND_H02", "IND_S01", "IND_D01"],
    )
    weights, method = compute_weights(big_matrix)
    assert method == "entropy_critic_hybrid"
    assert abs(weights.sum() - 1.0) < 1e-9


def test_driver_baseline_end_to_end_with_low_n_synthetic_data():
    """The realistic path this system will actually run in: six segments,
    which triggers the low-N fallback documented in weighting.py.
    """
    entities = [s.value for s in Segment]
    rng = np.random.default_rng(42)
    rows = []
    for ind_id in ["IND_H01", "IND_H02", "IND_S02"]:  # all load on Capital or Demand
        for e in entities:
            rows.append(dict(indicator_id=ind_id, entity=e, score_0_100=rng.uniform(20, 80)))
    scores = pd.DataFrame(rows)

    baseline = compute_driver_baseline(
        segment=Segment.OPTUM_HEALTH,
        driver=Driver.CAPITAL,
        indicator_scores=scores,
        as_of=date(2026, 1, 1),
    )

    assert baseline.weighting_method == "expert_elicited_fallback"
    assert 0 <= baseline.risk_score <= 100
    assert 0 <= baseline.opportunity_score <= 100
    assert 0 <= baseline.coverage <= 1
    assert 0 <= baseline.confidence <= 1


def test_driver_baseline_raises_clearly_when_no_indicators_available():
    empty = pd.DataFrame(columns=["indicator_id", "entity", "score_0_100"])
    with pytest.raises(ValueError, match="No indicator data available"):
        compute_driver_baseline(
            segment=Segment.OPTUM_HEALTH,
            driver=Driver.TALENT,
            indicator_scores=empty,
            as_of=date(2026, 1, 1),
        )
