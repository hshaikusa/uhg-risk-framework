"""Normalize and load OpenInference / Phoenix spans for eval scoring."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def normalize_span(record: dict[str, Any]) -> dict[str, Any]:
    """Normalize either a fixture dict or a Phoenix dataframe row-like mapping."""
    if "attributes" in record and isinstance(record["attributes"], dict):
        attrs = dict(record["attributes"])
    else:
        attrs = {}
        for key, value in record.items():
            if key.startswith("attributes."):
                attrs[key[len("attributes.") :]] = value

    kind = (
        record.get("span_kind")
        or attrs.get("openinference.span.kind")
        or "UNKNOWN"
    )
    return {
        "name": record.get("name") or "",
        "span_kind": str(kind),
        "status_code": str(record.get("status_code") or "UNSET"),
        "start_time": record.get("start_time"),
        "end_time": record.get("end_time"),
        "trace_id": record.get("trace_id") or record.get("context.trace_id"),
        "span_id": record.get("span_id") or record.get("context.span_id"),
        "attributes": attrs,
        "input_value": attrs.get("input.value"),
        "output_value": attrs.get("output.value"),
        "tool_name": attrs.get("tool.name") or attrs.get("mcp.tool"),
    }


def load_span_fixture(name: str = "sample_phoenix_spans.json") -> list[dict[str, Any]]:
    path = FIXTURES_DIR / name
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [normalize_span(r) for r in raw]


def fetch_phoenix_spans(
    *,
    project: str | None = None,
    base_url: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Pull recent spans from a running Phoenix instance (live observability)."""
    from phoenix.client import Client

    project = project or os.getenv("PHOENIX_PROJECT") or "uhg-risk-intelligence"
    base_url = (
        base_url
        or os.getenv("PHOENIX_BASE_URL")
        or os.getenv("PHOENIX_HOST")
        or "http://127.0.0.1:6006"
    )
    # Collector endpoint is .../v1/traces; client wants the UI/API root.
    if base_url.rstrip("/").endswith("/v1/traces"):
        base_url = base_url.rstrip("/")[: -len("/v1/traces")] or "http://127.0.0.1:6006"

    client = Client(base_url=base_url)
    df = client.spans.get_spans_dataframe(project_name=project, limit=limit)
    if df is None or len(df) == 0:
        return []

    # Prefer newest spans when Phoenix returns more than we need / unsorted.
    if "start_time" in df.columns:
        df = df.sort_values("start_time", ascending=False).head(limit)

    spans: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        record = row.to_dict()
        spans.append(normalize_span(record))
    return spans
