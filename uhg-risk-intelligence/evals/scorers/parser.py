from __future__ import annotations

from typing import Any, Iterable

from src.schemas import Driver, Disruptor, ScenarioQuery, Segment


def score_parser_prediction(
    predicted: ScenarioQuery | dict[str, Any],
    expected: dict[str, Any],
    *,
    min_driver_jaccard: float = 1.0,
) -> dict[str, Any]:
    """Exact-field scoring for query-parser evals.

    Pass rule: segment + disruptor exact, and drivers Jaccard >= min_driver_jaccard.
    Offline smoke uses 1.0 (exact). Live LLM runs typically use 0.5 because
    Capital vs Demand on rate/funding questions is legitimately ambiguous.
    """
    if isinstance(predicted, ScenarioQuery):
        seg = predicted.segment.value
        disruptor = predicted.disruptor.value
        drivers = {d.value for d in predicted.drivers}
    else:
        seg = predicted["segment"]
        disruptor = predicted["disruptor"]
        drivers = set(predicted["drivers"])

    exp_drivers = set(expected["drivers"])
    segment_ok = seg == expected["segment"]
    disruptor_ok = disruptor == expected["disruptor"]
    drivers_jaccard = (
        len(drivers & exp_drivers) / len(drivers | exp_drivers)
        if (drivers or exp_drivers)
        else 1.0
    )
    drivers_ok = drivers_jaccard >= min_driver_jaccard
    exact = segment_ok and disruptor_ok and drivers == exp_drivers
    passed = segment_ok and disruptor_ok and drivers_ok
    # Weighted score: segment/disruptor are hard requirements; drivers soft.
    score = (0.4 * segment_ok) + (0.4 * disruptor_ok) + (0.2 * drivers_jaccard)
    return {
        "passed": passed,
        "exact": exact,
        "segment_match": segment_ok,
        "disruptor_match": disruptor_ok,
        "drivers_exact": drivers == exp_drivers,
        "drivers_jaccard": round(drivers_jaccard, 3),
        "min_driver_jaccard": min_driver_jaccard,
        "score": round(score, 3),
        "predicted": {"segment": seg, "disruptor": disruptor, "drivers": sorted(drivers)},
        "expected": expected,
    }


def scenario_query_from_expected(question: str, expected: dict[str, Any]) -> ScenarioQuery:
    return ScenarioQuery(
        segment=Segment(expected["segment"]),
        drivers=[Driver(d) for d in expected["drivers"]],
        disruptor=Disruptor(expected["disruptor"]),
        raw_question=question,
    )


def mean(values: Iterable[float]) -> float:
    vals = list(values)
    return sum(vals) / len(vals) if vals else 0.0
