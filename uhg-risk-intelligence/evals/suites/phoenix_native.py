"""Phoenix-native eval suite wrapper."""

from __future__ import annotations

from typing import Any

from evals.phoenix_evals import run_phoenix_native_evals
from evals.traces import fetch_phoenix_spans
from evals.traces.summary import latest_run_spans
from evals.types import SuiteReport


def run_phoenix_evals_latest(
    *,
    limit: int = 200,
    annotate: bool = False,
    window_spans: list[dict[str, Any]] | None = None,
    mirror_span_id: str | None = None,
) -> SuiteReport:
    spans = window_spans if window_spans is not None else fetch_phoenix_spans(limit=limit)
    run_spans = latest_run_spans(spans) or spans
    return run_phoenix_native_evals(
        run_spans,
        annotate=annotate,
        mirror_span_id=mirror_span_id,
    )
