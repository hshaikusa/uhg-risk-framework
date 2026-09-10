"""Build Phoenix-eval DataFrames from normalized span payloads."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from evals.judges.phoenix_extract import (
    extract_narrative_from_spans,
    extract_overlay_from_spans,
    extract_retrieval_from_spans,
)


def _first_span_id(spans: list[dict[str, Any]], *, names: set[str] | None = None) -> str | None:
    for span in spans:
        if names and span.get("name") not in names:
            continue
        sid = span.get("span_id")
        if sid:
            return str(sid)
    for span in spans:
        sid = span.get("span_id")
        if sid:
            return str(sid)
    return None


def build_eval_dataframes(spans: list[dict[str, Any]]) -> dict[str, pd.DataFrame]:
    """Return one DataFrame per evaluator that has extractable inputs."""
    frames: dict[str, pd.DataFrame] = {}

    narr = extract_narrative_from_spans(spans)
    if narr:
        sid = (
            narr.get("span_id")
            or _first_span_id(spans, names={"generate_narrative", "ChatCompletion", "LangGraph"})
        )
        if sid:
            frames["narrative_faithfulness"] = pd.DataFrame(
                [
                    {
                        "span_id": sid,
                        "scenario_json": json.dumps(narr["scenario"], default=str),
                        "narrative_text": narr["narrative_text"],
                        "audience": narr.get("audience", "analyst"),
                    }
                ]
            )
            frames["narrative_style"] = pd.DataFrame(
                [
                    {
                        "span_id": sid,
                        "audience": narr.get("audience", "analyst"),
                        "narrative_text": narr["narrative_text"],
                    }
                ]
            )

    ret = extract_retrieval_from_spans(spans)
    if ret:
        sid = str(ret.get("span_id") or _first_span_id(spans, names={"tavily.search"}) or "")
        if sid:
            frames["retrieval_relevance"] = pd.DataFrame(
                [
                    {
                        "span_id": sid,
                        "query": ret.get("query") or "",
                        "segment": ret["segment"],
                        "driver": ret["driver"],
                        "retrieved_text": ret["retrieved_text"],
                    }
                ]
            )

    overlay = extract_overlay_from_spans(spans)
    if overlay:
        sid = str(overlay.get("span_id") or _first_span_id(spans, names={"ChatCompletion"}) or "")
        if sid:
            frames["overlay_calibration"] = pd.DataFrame(
                [
                    {
                        "span_id": sid,
                        "segment": overlay["segment"],
                        "driver": overlay["driver"],
                        "source_text": overlay["source_text"][:4000],
                        "proposed_rating_json": json.dumps(overlay["predicted"], default=str),
                    }
                ]
            )

    return frames
