from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from src.observability import retriever_span, set_span_output

logger = logging.getLogger(__name__)

SAMPLE_DATA_PATH = Path(__file__).parent.parent / "data" / "sample_overlay_texts.json"


def _load_bundled_sample(segment_value: str) -> dict | None:
    data = json.loads(SAMPLE_DATA_PATH.read_text())
    for sample in data["samples"]:
        if sample["segment"] == segment_value:
            return sample
    return None


def _record_search_result(span, *, text: str, source_label: str, live: bool) -> None:
    if span is not None:
        span.set_attribute("search.live", live)
        span.set_attribute("search.source", source_label)
    set_span_output(
        span,
        json.dumps(
            {
                "live": live,
                "source": source_label,
                "content_preview": text[:800],
            },
            indent=2,
        ),
    )


def search_for_overlay_input(query: str, segment_value: str) -> tuple[str, str]:
    """Returns (source_text, source_label). source_label is either a real
    URL (live search) or "bundled_fallback:<id>" so callers/logs can always
    tell which path was actually used.
    """
    with retriever_span(
        "tavily.search",
        query=query,
        provider="tavily",
        attributes={"segment": segment_value},
    ) as span:
        api_key = os.environ.get("TAVILY_API_KEY")
        if api_key:
            try:
                from tavily import TavilyClient

                client = TavilyClient(api_key=api_key)
                results = client.search(query=query, max_results=3)
                if results.get("results"):
                    top = results["results"][0]
                    text = top.get("content", "")
                    source_label = top.get("url", "live_search_no_url")
                    _record_search_result(span, text=text, source_label=source_label, live=True)
                    return text, source_label
                if span is not None:
                    span.set_attribute("search.empty_results", True)
            except Exception as e:
                if span is not None:
                    span.set_attribute("search.error", str(e))
                logger.warning("Live search failed (%s); falling back to bundled sample data.", e)

        sample = _load_bundled_sample(segment_value)
        if sample is None:
            raise ValueError(f"No bundled fallback sample available for segment={segment_value}")
        text, source_label = sample["text"], f"bundled_fallback:{sample['id']}"
        _record_search_result(span, text=text, source_label=source_label, live=False)
        return text, source_label
