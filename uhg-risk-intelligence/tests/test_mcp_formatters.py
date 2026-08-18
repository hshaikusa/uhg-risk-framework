import json

from src.mcp.formatters import format_tool_result_lines, parse_tool_payload, print_tool_result


SAMPLE_TICKER = {
    "symbol": "UNH",
    "longName": "UnitedHealth Group Incorporated",
    "sector": "Healthcare",
    "industry": "Healthcare Plans",
    "currentPrice": 407.08,
    "previousClose": 403.97,
    "regularMarketChangePercent": 0.77,
    "marketCap": 369_687_396_352,
    "trailingPE": 30.7,
    "forwardPE": 18.1,
    "fiftyTwoWeekLow": 252.14,
    "fiftyTwoWeekHigh": 461.62,
    "dividendYield": 0.0228,
    "recommendationKey": "buy",
    "targetMeanPrice": 475.23,
    "longBusinessSummary": "UnitedHealth Group operates through Optum and UnitedHealthcare.",
}


def test_parse_tool_payload_unwraps_result_envelope():
    inner = json.dumps(SAMPLE_TICKER)
    wrapped = json.dumps({"result": inner})
    assert parse_tool_payload(wrapped)["symbol"] == "UNH"


def test_format_ticker_analyst():
    raw = json.dumps({"result": json.dumps(SAMPLE_TICKER)})
    lines = format_tool_result_lines("yfmcp", "yfinance_get_ticker_info", raw, audience="analyst")
    text = "\n".join(lines)
    assert "Symbol:      UNH" in text
    assert "Market cap:" in text
    assert "supplemental parent-company context" in text


def test_format_ticker_executive_one_line():
    raw = json.dumps(SAMPLE_TICKER)
    lines = format_tool_result_lines("yfmcp", "yfinance_get_ticker_info", raw, audience="executive")
    assert len(lines) == 3  # header, rule, one summary line
    assert "+0.77%" in lines[-1]
    assert "UNH" in lines[-1]
    assert "supplemental" in lines[-1]


def test_format_backtest_anchors():
    raw = json.dumps({
        "anchors": [{
            "id": "test_anchor",
            "segment": "Optum_Health",
            "driver": "Capital",
            "disruptor": "D6_political_regulatory_volatility",
            "description": "Sample event",
        }],
    })
    lines = format_tool_result_lines("local", "get_backtest_anchors", raw)
    text = "\n".join(lines)
    assert "test_anchor" in text
    assert "Sample event" in text
