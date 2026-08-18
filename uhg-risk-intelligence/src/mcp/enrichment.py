from __future__ import annotations

import logging

from src.ai_steps.search_tool import search_for_overlay_input
from src.mcp.client import call_tool, list_all_tools
from src.mcp.config import load_server_configs, mcp_enabled
from src.mcp.formatters import print_tool_result

logger = logging.getLogger(__name__)


def print_mcp_context() -> None:
    """Supplemental, non-authoritative context after a successful scenario run."""
    if not mcp_enabled():
        print("\n[MCP CONTEXT — disabled (MCP_ENABLED=false)]")
        return

    print("\n" + "=" * 70)
    print("[MCP CONTEXT — supplemental only; does NOT affect scenario scores]")
    print("=" * 70)

    servers = load_server_configs()
    if "yfmcp" in servers:
        try:
            text = call_tool("yfmcp", "yfinance_get_ticker_info", {"symbol": "UNH"})
            print()
            print_tool_result("yfmcp", "yfinance_get_ticker_info", text, audience="analyst")
            return
        except Exception as exc:
            logger.warning("yfmcp ticker info failed: %s", exc)
            print(f"\n[yfmcp unavailable: {exc}]")

    try:
        text = call_tool("local", "get_backtest_anchors", {})
        print()
        print_tool_result("local", "get_backtest_anchors", text, audience="analyst")
    except Exception as exc:
        print(f"\n[MCP context unavailable: {exc}]")


def search_via_mcp_or_fallback(query: str, segment_value: str) -> tuple[str, str]:
    """Try an MCP search-like tool first; fall back to Tavily/bundled search."""
    if mcp_enabled():
        for tool in list_all_tools():
            if "search" not in tool.name.lower():
                continue
            try:
                text = call_tool(
                    tool.server,
                    tool.name,
                    {"query": query, "q": query, "search_term": query},
                )
                if text.strip():
                    return text, f"mcp:{tool.server}.{tool.name}"
            except Exception as exc:
                logger.warning("MCP search tool %s.%s failed: %s", tool.server, tool.name, exc)

    return search_for_overlay_input(query, segment_value)
