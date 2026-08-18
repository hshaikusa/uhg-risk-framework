"""
Layer 1-2: query parser.

Turns a natural-language question into a schema-validated ScenarioQuery.
Uses the small/fast model tier — see README "Model tiers" — because this is
a low-ambiguity structured-extraction task, not a judgment call.

NOTE: requires OPENAI_API_KEY (or ANTHROPIC_API_KEY, see get_client below)
in the environment. Not executable in a sandboxed environment without one —
see tests/test_graph_mocked.py for how the graph's control flow is verified
without live API calls.
"""
from __future__ import annotations

import os

import instructor
from openai import OpenAI

from src.guardrails.gates import GuardrailRejection, validate_query
from src.schemas import ParseFailure, ScenarioQuery

from src.observability import make_openai_client # Hash: new addition for observability


FAST_MODEL = os.environ.get("FAST_MODEL", "gpt-4o-mini")

SYSTEM_PROMPT = """You parse a natural-language question about UnitedHealth \
Group's exposure to a business disruptor into a structured query. Only use \
segment, driver, and disruptor values that exist in the provided schema.

If the question is NOT about UHG/Optum/UHC segment exposure (e.g. general \
stock prices, unrelated companies, trivia), still populate the schema fields \
as best you can — a downstream validator will reject it as out_of_scope.

If the question references a retired or divested segment (international, \
global, etc.), populate fields but the downstream validator will reject it.

For in-scope questions, map segment, driver, and disruptor faithfully; do \
not silently omit fields."""


def get_client() -> instructor.Instructor:
    return instructor.from_openai(make_openai_client())

def parse_query(question: str) -> ScenarioQuery | ParseFailure:
    """Returns a validated ScenarioQuery, or a ParseFailure the graph routes
    to a clarification request. Never returns a best-guess object that
    skipped validation.
    """
    client = get_client()
    try:
        raw: ScenarioQuery = client.chat.completions.create(
            model=FAST_MODEL,
            response_model=ScenarioQuery,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
        )
    except Exception as e:  # instructor raises on schema-validation failure
        return ParseFailure(reason="ambiguous", raw_question=question, suggestion=str(e))

    try:
        return validate_query(raw)
    except GuardrailRejection as e:
        return ParseFailure(reason=e.reason, raw_question=question, suggestion=e.detail)
