import os
from unittest.mock import patch

from src.env_loader import load_project_env


def test_load_project_env_reads_dotenv(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("TEST_DOTENV_KEY=hello\n", encoding="utf-8")
    monkeypatch.delenv("TEST_DOTENV_KEY", raising=False)
    with patch("src.env_loader._PROJECT_ROOT", tmp_path):
        assert load_project_env() is True
    assert os.getenv("TEST_DOTENV_KEY") == "hello"


def test_load_project_env_missing_file(tmp_path):
    with patch("src.env_loader._PROJECT_ROOT", tmp_path):
        assert load_project_env() is False
