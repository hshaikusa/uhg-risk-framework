from __future__ import annotations

from typing import Any


ORDINAL_FIELDS = ("severity_0_to_3", "immediacy_0_to_3", "persistence_0_to_3")


def _within_rater_band(pred: int, a: int, b: int, tolerance: int = 1) -> bool:
    """Pass if pred is inside [min(a,b)-tol, max(a,b)+tol] clipped to 0-3."""
    lo = max(0, min(a, b) - tolerance)
    hi = min(3, max(a, b) + tolerance)
    return lo <= pred <= hi


def score_overlay_against_double_raters(
    predicted: dict[str, Any],
    rater_a: dict[str, Any],
    rater_b: dict[str, Any],
    *,
    tolerance: int = 1,
) -> dict[str, Any]:
    """Calibration score for subjective 0-3 fields vs two independent raters.

    - sign must match at least one rater (prefer both)
    - each ordinal field passes within the double-rater ±tolerance band
    - MAE is vs the mean of the two raters
    """
    field_results: dict[str, Any] = {}
    abs_errors: list[float] = []
    within = 0

    sign_a = rater_a["sign"]
    sign_b = rater_b["sign"]
    sign_ok = predicted.get("sign") in {sign_a, sign_b}
    sign_both = sign_a == sign_b and predicted.get("sign") == sign_a

    for field in ORDINAL_FIELDS:
        pred = int(predicted[field])
        a = int(rater_a[field])
        b = int(rater_b[field])
        ok = _within_rater_band(pred, a, b, tolerance=tolerance)
        mae = abs(pred - (a + b) / 2)
        abs_errors.append(mae)
        if ok:
            within += 1
        field_results[field] = {
            "predicted": pred,
            "rater_a": a,
            "rater_b": b,
            "within_band": ok,
            "mae_vs_mean": round(mae, 3),
        }

    ordinal_rate = within / len(ORDINAL_FIELDS)
    mean_mae = sum(abs_errors) / len(abs_errors) if abs_errors else 0.0
    # Pass rule: sign ok + all ordinal fields within band (tolerance already ±1)
    passed = sign_ok and within == len(ORDINAL_FIELDS)
    score = (0.25 * float(sign_ok)) + (0.75 * ordinal_rate)

    return {
        "passed": passed,
        "score": round(score, 3),
        "sign_ok": sign_ok,
        "sign_both_raters_agree_and_match": sign_both,
        "ordinal_within_band_rate": round(ordinal_rate, 3),
        "mean_mae": round(mean_mae, 3),
        "fields": field_results,
    }
