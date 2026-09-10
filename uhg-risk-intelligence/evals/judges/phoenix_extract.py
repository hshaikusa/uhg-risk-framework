"""Extract narrative / retrieval / overlay payloads from Phoenix spans for judging."""

from __future__ import annotations

import json
import re
from typing import Any


def _parse_jsonish(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _scenario_from_repr(text: str) -> dict[str, Any] | None:
    """Best-effort parse of ScenarioOutput-like repr / json fragments in span I/O."""
    if not text:
        return None

    def _enum_or_str(raw: str) -> str:
        m = re.search(r"['\"]([A-Za-z0-9_]+)['\"]", raw)
        return m.group(1) if m else raw.strip()

    fields: dict[str, Any] = {}
    for key in (
        "segment",
        "disruptor",
        "driver",
        "final_risk",
        "final_opportunity",
        "recommended_pathway",
        "net_strategic_value",
        "confidence",
        "below_confidence_floor",
    ):
        m = re.search(rf"{key}\s*=\s*([^,\n]+)", text)
        if not m:
            # JSON style
            m = re.search(rf'"{key}"\s*:\s*([^,\n\}}]+)', text)
        if not m:
            continue
        raw = m.group(1).strip()
        if key in {"final_risk", "final_opportunity", "net_strategic_value", "confidence"}:
            try:
                fields[key] = float(re.search(r"-?\d+(?:\.\d+)?", raw).group())  # type: ignore[union-attr]
            except (AttributeError, ValueError):
                continue
        elif key == "below_confidence_floor":
            fields[key] = "true" in raw.lower()
        elif key == "recommended_pathway":
            if "None" in raw or raw.lower() == "null":
                fields[key] = None
            else:
                fields[key] = _enum_or_str(raw)
        else:
            fields[key] = _enum_or_str(raw)

    required = {"segment", "driver", "disruptor", "final_risk", "final_opportunity", "confidence"}
    if not required.issubset(fields):
        return None
    fields.setdefault("below_confidence_floor", False)
    fields.setdefault("recommended_pathway", None)
    fields.setdefault("net_strategic_value", None)
    return fields


def extract_narrative_from_spans(spans: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pull scenario + narrative text + audience from a latest-run span set."""
    audience = "analyst"
    scenario: dict[str, Any] | None = None
    narrative_text: str | None = None
    anchor_span_id: str | None = None

    def _maybe_narrative_from_blob(blob: str) -> str | None:
        if not blob:
            return None
        # NarrativeOutput / state dumps often look like: text='...' or "text": "..."
        for pat in (
            r'"text"\s*:\s*"((?:\\.|[^"\\])*)"',
            r"text='((?:\\'|[^']){40,})'",
            r'text="((?:\\"|[^"]){40,})"',
            r'"content"\s*:\s*"((?:\\.|[^"\\])*)"',
        ):
            m = re.search(pat, blob)
            if not m:
                continue
            raw = m.group(1)
            try:
                candidate = json.loads(f'"{raw}"')
            except json.JSONDecodeError:
                candidate = (
                    raw.replace("\\'", "'")
                    .replace('\\"', '"')
                    .replace("\\n", "\n")
                )
            if any(tok in candidate.lower() for tok in ("risk", "pathway", "optum", "uhc", "opportunity")):
                return candidate
        return None

    for span in spans:
        out = span.get("output_value")
        inp = span.get("input_value")
        parsed = _parse_jsonish(out)
        if isinstance(parsed, dict):
            if parsed.get("audience"):
                audience = str(parsed["audience"]).lower()
            narr = parsed.get("narrative")
            if isinstance(narr, dict) and narr.get("text"):
                narrative_text = str(narr["text"])
                anchor_span_id = str(span.get("span_id") or "") or anchor_span_id
                if isinstance(narr.get("source_scenario"), dict):
                    scenario = narr["source_scenario"]
                elif isinstance(parsed.get("scenario"), dict):
                    scenario = parsed["scenario"]
            elif isinstance(narr, str) and len(narr) > 40:
                # Sometimes serialized as a repr/string on state
                maybe = _maybe_narrative_from_blob(narr) or (
                    narr if any(t in narr.lower() for t in ("risk", "optum", "uhc")) else None
                )
                if maybe:
                    narrative_text = maybe
                    anchor_span_id = str(span.get("span_id") or "") or anchor_span_id
            sc = parsed.get("scenario")
            if scenario is None and isinstance(sc, dict):
                scenario = sc
            elif scenario is None and isinstance(sc, str):
                scenario = _scenario_from_repr(sc)

        if scenario is None:
            scenario = _scenario_from_repr(str(out or "")) or _scenario_from_repr(str(inp or ""))

        if narrative_text is None:
            maybe = _maybe_narrative_from_blob(str(out or ""))
            name = str(span.get("name") or "")
            prefer = name in {"generate_narrative", "ChatCompletion", "LangGraph"} or (
                "generate_narrative" in name
            )
            if maybe and prefer:
                narrative_text = maybe
                anchor_span_id = str(span.get("span_id") or "") or anchor_span_id
            elif maybe and narrative_text is None and any(
                t in maybe.lower() for t in ("risk", "optum", "uhc")
            ):
                narrative_text = maybe
                anchor_span_id = str(span.get("span_id") or "") or anchor_span_id

    if scenario is None or not narrative_text:
        return None
    return {
        "scenario": scenario,
        "narrative_text": narrative_text,
        "audience": audience,
        "span_id": anchor_span_id,
    }


def extract_retrieval_from_spans(spans: list[dict[str, Any]]) -> dict[str, Any] | None:
    retrievers = [
        s
        for s in spans
        if s.get("span_kind") == "RETRIEVER" or s.get("name") == "tavily.search"
    ]
    if not retrievers:
        return None
    span = retrievers[0]
    out = span.get("output_value")
    inp = str(span.get("input_value") or "")
    preview = str(out or "")
    parsed = _parse_jsonish(out)
    if isinstance(parsed, dict):
        preview = str(parsed.get("content_preview") or preview)

    ql = inp.lower()
    segment, driver = "Optum_Health", "Capital"
    if "insight" in ql or "cyber" in ql or "security" in ql:
        segment, driver = "Optum_Insight", "Data_Digital"
    elif "rx" in ql:
        segment, driver = "Optum_Rx", "Supply"

    return {
        "query": inp,
        "segment": segment,
        "driver": driver,
        "retrieved_text": preview,
        "span_id": span.get("span_id"),
    }


def extract_overlay_from_spans(spans: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Find overlay extract tool-call args in ChatCompletion spans."""
    for span in spans:
        if span.get("name") not in {"ChatCompletion", "extract_overlay_event"}:
            continue
        blob = str(span.get("output_value") or "")
        if "severity_0_to_3" not in blob:
            continue
        # Tool-call arguments are often JSON-escaped inside the completion payload.
        normalized = blob.replace('\\"', '"').replace("\\n", "\n")

        sign_m = re.search(r'"sign"\s*:\s*"(risk|opportunity)"', normalized)
        sev = re.search(r'"severity_0_to_3"\s*:\s*(\d)', normalized)
        imm = re.search(r'"immediacy_0_to_3"\s*:\s*(\d)', normalized)
        per = re.search(r'"persistence_0_to_3"\s*:\s*(\d)', normalized)
        if not (sign_m and sev and imm and per):
            continue
        predicted = {
            "sign": sign_m.group(1),
            "severity_0_to_3": int(sev.group(1)),
            "immediacy_0_to_3": int(imm.group(1)),
            "persistence_0_to_3": int(per.group(1)),
        }

        inp = str(span.get("input_value") or "")
        source = inp
        seg_m = re.search(r"segment[=:\s]+([A-Za-z_]+)", inp, re.I)
        drv_m = re.search(r"driver[=:\s]+([A-Za-z_]+)", inp, re.I)
        return {
            "source_text": source[:4000],
            "segment": seg_m.group(1) if seg_m else "Optum_Insight",
            "driver": drv_m.group(1) if drv_m else "Data_Digital",
            "predicted": predicted,
            "span_id": span.get("span_id"),
        }
    return None
