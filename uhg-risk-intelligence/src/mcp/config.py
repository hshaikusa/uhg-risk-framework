from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "mcp_servers.json"


@dataclass
class ServerConfig:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    cwd: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    optional: bool = False


def _default_servers() -> dict[str, ServerConfig]:
    root = str(PROJECT_ROOT)
    py = sys.executable
    return {
        "local": ServerConfig(
            name="local",
            command=py,
            args=["-m", "src.mcp.local_server"],
            cwd=root,
            env={**os.environ, "PYTHONPATH": root},
        ),
    }


def load_server_configs() -> dict[str, ServerConfig]:
    """Load MCP server definitions from mcp_servers.json, merged with the
    built-in local schema/backtest server so `tool list` always has something
    to show without extra setup.
    """
    servers = _default_servers()
    if not CONFIG_PATH.exists():
        return servers

    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    for name, spec in raw.get("servers", {}).items():
        if name == "local":
            continue  # built-in local server wins
        env = {**os.environ, **spec.get("env", {})}
        if "PYTHONPATH" not in spec.get("env", {}):
            env.setdefault("PYTHONPATH", str(PROJECT_ROOT))
        servers[name] = ServerConfig(
            name=name,
            command=spec["command"],
            args=spec.get("args", []),
            cwd=spec.get("cwd", str(PROJECT_ROOT)),
            env=env,
            optional=spec.get("optional", False),
        )
    return servers


def mcp_enabled() -> bool:
    return os.getenv("MCP_ENABLED", "true").lower() not in ("0", "false", "no")
