from __future__ import annotations

import json
from typing import Any


def parse_tool_payload(raw: str) -> Any:
    """Unwrap MCP tool text — handles nested {\"result\": \"...\"} envelopes."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw

    if isinstance(data, dict) and set(data.keys()) == {"result"}:
        inner = data["result"]
        if isinstance(inner, str):
            try:
                return json.loads(inner)
            except json.JSONDecodeError:
                return inner
        return inner
    return data


def _fmt_usd(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(num) >= 1_000_000_000_000:
        return f"${num / 1_000_000_000_000:.2f}T"
    if abs(num) >= 1_000_000_000:
        return f"${num / 1_000_000_000:.1f}B"
    if abs(num) >= 1_000_000:
        return f"${num / 1_000_000:.1f}M"
    return f"${num:,.2f}"


def _fmt_pct_decimal(value: Any, *, signed: bool = False) -> str:
    """Format a ratio (e.g. dividendYield 0.0228 → 2.28%)."""
    if value is None:
        return "n/a"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    pct = num * 100
    if signed and pct > 0:
        return f"+{pct:.2f}%"
    return f"{pct:.2f}%"


def _fmt_pct_points(value: Any, *, signed: bool = False) -> str:
    """Format an already-percent value (e.g. regularMarketChangePercent 0.77 → 0.77%)."""
    if value is None:
        return "n/a"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if signed and num > 0:
        return f"+{num:.2f}%"
    return f"{num:.2f}%"


def _first(data: dict, *keys: str, default: str = "n/a") -> str:
    for key in keys:
        val = data.get(key)
        if val is not None and val != "":
            return str(val)
    return default


def _format_ticker_info(data: dict, audience: str) -> list[str]:
    symbol = _first(data, "symbol")
    name = _first(data, "longName", "shortName")
    sector = _first(data, "sector")
    industry = _first(data, "industry")
    price = data.get("currentPrice") or data.get("regularMarketPrice")
    prev = data.get("previousClose") or data.get("regularMarketPreviousClose")
    change_pct = data.get("regularMarketChangePercent")
    market_cap = _fmt_usd(data.get("marketCap"))
    trailing_pe = data.get("trailingPE")
    forward_pe = data.get("forwardPE")
    low52 = data.get("fiftyTwoWeekLow")
    high52 = data.get("fiftyTwoWeekHigh")
    div_yield = data.get("dividendYield")
    rec = _first(data, "recommendationKey", default="")
    target = data.get("targetMeanPrice")
    summary = _first(data, "longBusinessSummary", default="")

    if audience == "executive":
        change_txt = _fmt_pct_points(change_pct, signed=True) if change_pct is not None else "n/a"
        line = (
            f"{symbol} ({name}) trades at {_fmt_usd(price)} ({change_txt} vs prior close), "
            f"{market_cap} market cap — supplemental parent-company context only, "
            f"not a UHG segment risk score."
        )
        return [line]

    lines = [
        f"Symbol:      {symbol}",
        f"Company:     {name}",
        f"Sector:      {sector} / {industry}",
        f"Price:       {_fmt_usd(price)}  (prev {_fmt_usd(prev)}, "
        f"{_fmt_pct_points(change_pct, signed=True) if change_pct is not None else 'n/a'})",
        f"Market cap:  {market_cap}",
        f"P/E (ttm):   {trailing_pe if trailing_pe is not None else 'n/a'}"
        f"  |  Forward P/E: {forward_pe if forward_pe is not None else 'n/a'}",
        f"52-wk range: {_fmt_usd(low52)} – {_fmt_usd(high52)}",
        f"Dividend:    {_fmt_pct_decimal(div_yield) if div_yield is not None else 'n/a'} yield",
    ]
    if rec and rec != "n/a":
        target_txt = _fmt_usd(target) if target is not None else "n/a"
        lines.append(f"Analyst view: {rec.title()} (mean target {target_txt})")
    if summary and summary != "n/a":
        snippet = summary[:320].rstrip() + ("..." if len(summary) > 320 else "")
        lines.extend(["", "Business summary:", f"  {snippet}"])
    lines.append("")
    lines.append("Note: market data is supplemental parent-company context — "
                 "it does NOT affect scenario scores.")
    return lines


def _format_schema(data: dict) -> list[str]:
    lines = ["Allowed ontology values:"]
    for label, key in (
        ("Segments", "segments"),
        ("Drivers", "drivers"),
        ("Disruptors", "disruptors"),
    ):
        values = data.get(key) or []
        lines.append(f"\n  [{label}]")
        for item in values:
            lines.append(f"    - {item}")
    return lines


def _format_backtest_anchors(data: dict) -> list[str]:
    lines = []
    prov = data.get("_provenance")
    if prov:
        lines.extend(["Provenance:", f"  {prov}", ""])
    lines.append("Backtest anchors:")
    for anchor in data.get("anchors") or []:
        lines.append(f"\n  [{anchor.get('id', 'unknown')}]")
        lines.append(f"    Segment:   {anchor.get('segment', 'n/a')}")
        lines.append(f"    Driver:    {anchor.get('driver', 'n/a')}")
        lines.append(f"    Disruptor: {anchor.get('disruptor', 'n/a')}")
        lines.append(f"    Event:     {anchor.get('description', 'n/a')}")
        question = anchor.get("backtest_question")
        if question:
            lines.append(f"    Question:  {question}")
    return lines


def format_tool_result_lines(
    server: str,
    tool: str,
    raw: str,
    *,
    audience: str = "analyst",
) -> list[str]:
    payload = parse_tool_payload(raw)
    header = f"[MCP TOOL RESULT — {server}.{tool}]"
    if audience == "executive":
        header += " (executive summary)"

    if isinstance(payload, dict):
        if tool == "yfinance_get_ticker_info":
            body = _format_ticker_info(payload, audience)
        elif tool == "list_schema":
            body = _format_schema(payload)
        elif tool == "get_backtest_anchors":
            body = _format_backtest_anchors(payload)
        else:
            body = [json.dumps(payload, indent=2, default=str)]
    elif isinstance(payload, list):
        body = [json.dumps(payload, indent=2, default=str)]
    else:
        body = [str(payload)]

    return [header, "=" * 70, *body]


def print_tool_result(
    server: str,
    tool: str,
    raw: str,
    *,
    audience: str = "analyst",
    raw_output: bool = False,
) -> None:
    if raw_output:
        print("\n[MCP TOOL RESULT — raw JSON]")
        print("=" * 70)
        print(raw)
        return

    for line in format_tool_result_lines(server, tool, raw, audience=audience):
        print(line)
