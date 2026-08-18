from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent

from src.mcp.config import ServerConfig, load_server_configs, mcp_enabled
from src.observability import mcp_span, set_mcp_span_output


@dataclass
class ToolInfo:
    server: str
    name: str
    description: str


def _tool_result_to_text(result: Any) -> str:
    if getattr(result, "isError", False):
        parts = []
        for block in result.content or []:
            if isinstance(block, TextContent):
                parts.append(block.text)
        raise RuntimeError("".join(parts) or "MCP tool returned an error")

    if getattr(result, "structuredContent", None):
        return json.dumps(result.structuredContent, indent=2, default=str)

    parts: list[str] = []
    for block in result.content or []:
        if isinstance(block, TextContent):
            parts.append(block.text)
    return "\n".join(parts) if parts else str(result)


async def _with_session(server: ServerConfig, fn):
    params = StdioServerParameters(
        command=server.command,
        args=server.args,
        env=server.env,
        cwd=server.cwd,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await fn(session)


async def _list_tools_async(server: ServerConfig) -> list[ToolInfo]:
    async def _inner(session: ClientSession):
        response = await session.list_tools()
        return [
            ToolInfo(server=server.name, name=t.name, description=t.description or "")
            for t in response.tools
        ]

    return await _with_session(server, _inner)


async def _call_tool_async(server: ServerConfig, tool_name: str, arguments: dict[str, Any]) -> str:
    async def _inner(session: ClientSession):
        result = await session.call_tool(tool_name, arguments=arguments)
        return _tool_result_to_text(result)

    return await _with_session(server, _inner)


def list_all_tools() -> list[ToolInfo]:
    if not mcp_enabled():
        return []
    tools: list[ToolInfo] = []
    with mcp_span("mcp.list_tools", span_kind="CHAIN") as span:
        for name, cfg in load_server_configs().items():
            with mcp_span("mcp.list_tools.server", server=name, span_kind="CHAIN") as server_span:
                try:
                    server_tools = asyncio.run(_list_tools_async(cfg))
                    tools.extend(server_tools)
                    if server_span is not None:
                        server_span.set_attribute("mcp.tool_count", len(server_tools))
                except Exception as exc:
                    if not cfg.optional:
                        raise RuntimeError(f"MCP server '{name}' failed: {exc}") from exc
        if span is not None:
            span.set_attribute("mcp.total_tools", len(tools))
    return tools


def call_tool(server_name: str, tool_name: str, arguments: dict[str, Any] | None = None) -> str:
    if not mcp_enabled():
        raise RuntimeError("MCP is disabled (set MCP_ENABLED=true to use MCP tools)")
    servers = load_server_configs()
    if server_name not in servers:
        raise KeyError(f"Unknown MCP server '{server_name}'. Known: {list(servers)}")
    args = arguments or {}
    with mcp_span(
        "mcp.call_tool",
        server=server_name,
        tool=tool_name,
        arguments=args,
    ) as span:
        result = asyncio.run(_call_tool_async(servers[server_name], tool_name, args))
        set_mcp_span_output(span, result)
        return result


def parse_tool_ref(tool_ref: str) -> tuple[str, str]:
    if "." not in tool_ref:
        raise ValueError(f"Tool reference must be server.tool_name, got: {tool_ref!r}")
    server, tool = tool_ref.split(".", 1)
    return server, tool


# Common CLI aliases → MCP tool parameter names (e.g. yfmcp uses "symbol").
_TOOL_ARG_ALIASES = {"ticker": "symbol"}


def parse_tool_arguments(tokens: list[str] | None = None) -> dict[str, str]:
    """Parse trailing tool-call tokens: --arg key=value, --key value, or key=value."""
    out: dict[str, str] = {}
    tokens = list(tokens or [])
    if tokens and tokens[0] == "--":
        tokens = tokens[1:]

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "--arg":
            if i + 1 >= len(tokens):
                raise ValueError("--arg requires a key=value argument (e.g. --arg symbol=UNH)")
            item = tokens[i + 1]
            if "=" not in item:
                raise ValueError(
                    f"Expected key=value after --arg, got: {item!r}. Example: --arg symbol=UNH"
                )
            key, value = item.split("=", 1)
            key = _TOOL_ARG_ALIASES.get(key.strip(), key.strip())
            out[key] = value.strip()
            i += 2
            continue
        if tok.startswith("--arg="):
            item = tok[6:]
            if "=" not in item:
                raise ValueError(
                    f"Expected key=value after --arg=, got: {item!r}. Example: --arg=symbol=UNH"
                )
            key, value = item.split("=", 1)
            key = _TOOL_ARG_ALIASES.get(key.strip(), key.strip())
            out[key] = value.strip()
            i += 1
            continue
        if tok.startswith("--"):
            key = tok[2:].replace("-", "_")
            key = _TOOL_ARG_ALIASES.get(key, key)
            if i + 1 >= len(tokens) or tokens[i + 1].startswith("--"):
                out[key] = "true"
                i += 1
            else:
                out[key] = tokens[i + 1]
                i += 2
            continue
        if "=" in tok:
            key, value = tok.split("=", 1)
            key = _TOOL_ARG_ALIASES.get(key.strip(), key.strip())
            out[key] = value.strip()
            i += 1
            continue
        raise ValueError(
            f"Unexpected tool argument {tok!r}. "
            "Use --arg symbol=UNH, --symbol UNH, or symbol=UNH."
        )
    return out
