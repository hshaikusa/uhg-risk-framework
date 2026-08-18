"""Built-in read-only MCP server — schema + backtest anchors for demos."""

from __future__ import annotations

import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from src.schemas import Disruptor, Driver, Segment

mcp = FastMCP("uhg-risk-local")
_DATA = Path(__file__).resolve().parent.parent / "data"


@mcp.tool()
def list_schema() -> str:
    """List allowed segments, drivers, and disruptors for UHG risk queries."""
    return json.dumps(
        {
            "segments": [s.value for s in Segment],
            "drivers": [d.value for d in Driver],
            "disruptors": [d.value for d in Disruptor],
        },
        indent=2,
    )


@mcp.tool()
def get_backtest_anchors() -> str:
    """Return real public backtest anchor events from data/backtest_anchors.json."""
    path = _DATA / "backtest_anchors.json"
    return path.read_text(encoding="utf-8")


if __name__ == "__main__":
    mcp.run()
