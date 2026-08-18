"""Load project .env before observability and API clients initialize."""

from __future__ import annotations

from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_project_env() -> bool:
    """Load .env from the repo root. Returns True if the file was found."""
    env_path = _PROJECT_ROOT / ".env"
    if not env_path.is_file():
        return False
    from dotenv import load_dotenv

    load_dotenv(env_path, override=False)
    return True
