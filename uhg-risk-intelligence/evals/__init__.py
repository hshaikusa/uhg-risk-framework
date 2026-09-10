"""Offline-first evaluation suites for UHG Risk Intelligence.

Run:
  python -m evals                 # offline suites (no API key)
  python -m evals --live          # also run LLM-backed suites
  pytest tests/test_evals_offline.py
"""

from evals.types import CaseResult, SuiteReport

__all__ = ["CaseResult", "SuiteReport"]
