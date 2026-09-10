"""Shared Instructor client for LLM-as-judge evals."""

from __future__ import annotations

import os
from typing import TypeVar

import instructor
from pydantic import BaseModel

from src.observability import make_openai_client

# Dedicated judge tier — distinct from FAST_MODEL (parser/narrative) and
# STRONG_MODEL (overlay extractor). Override via JUDGE_MODEL in .env.
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "gpt-4.1-mini")
MIN_JUDGE_SCORE = 0.7

T = TypeVar("T", bound=BaseModel)


def get_judge_client() -> instructor.Instructor:
    return instructor.from_openai(make_openai_client())


def judge_structured(
    *,
    system: str,
    user: str,
    response_model: type[T],
    model: str | None = None,
) -> T:
    client = get_judge_client()
    return client.chat.completions.create(
        model=model or JUDGE_MODEL,
        temperature=0,
        response_model=response_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
