from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def load_jsonl(name: str) -> list[dict[str, Any]]:
    path = FIXTURES_DIR / name
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def iter_jsonl(name: str) -> Iterator[dict[str, Any]]:
    yield from load_jsonl(name)
