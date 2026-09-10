"""Unit tests for Phoenix-eval dataframe builders (no API / Phoenix server)."""

from evals.phoenix_evals.dataframe import build_eval_dataframes
from evals.traces import load_span_fixture


def test_build_eval_dataframes_from_sample_spans():
    spans = load_span_fixture("sample_phoenix_spans.json")
    frames = build_eval_dataframes(spans)
    # Sample fixture has retriever + overlay extract; narrative text often missing.
    assert "retrieval_relevance" in frames
    assert "overlay_calibration" in frames
    needed = {"span_id", "query", "segment", "driver", "retrieved_text"}
    assert needed.issubset(set(frames["retrieval_relevance"].columns))
    assert "proposed_rating_json" in frames["overlay_calibration"].columns
