"""LLM judge for retrieval snippet relevance."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from evals.judges.client import MIN_JUDGE_SCORE, judge_structured

RETRIEVAL_SYSTEM = """You judge whether a retrieved news/policy snippet is relevant
to a UHG risk query about a given segment and driver.

relevant=true only if the snippet substantively relates to that segment/driver
risk theme (healthcare finance, cyber, supply, policy, etc. as appropriate).
Generic weather or unrelated market noise → relevant=false.
score is relevance confidence in [0,1].
"""


class RetrievalJudgeVerdict(BaseModel):
    relevant: bool
    reasons: list[str] = Field(default_factory=list)
    score: float = Field(ge=0.0, le=1.0)
    rationale: str


def judge_retrieval_relevance(
    *,
    retrieved_text: str,
    segment: str,
    driver: str,
    query: str | None = None,
) -> RetrievalJudgeVerdict:
    payload = {
        "query": query,
        "segment": segment,
        "driver": driver,
        "retrieved_text": retrieved_text,
    }
    return judge_structured(
        system=RETRIEVAL_SYSTEM,
        user=json.dumps(payload, indent=2),
        response_model=RetrievalJudgeVerdict,
    )


def score_retrieval_judge_verdict(
    verdict: RetrievalJudgeVerdict | dict[str, Any],
    *,
    expect_relevant: bool | None = None,
    min_score: float = MIN_JUDGE_SCORE,
) -> dict[str, Any]:
    if isinstance(verdict, RetrievalJudgeVerdict):
        data = verdict.model_dump()
    else:
        data = dict(verdict)

    relevant = bool(data.get("relevant"))
    score = float(data.get("score") or 0.0)
    # score = judge confidence in its relevant true/false call.
    confident = score >= min_score

    label_agree: bool | None = None
    if expect_relevant is not None:
        label_agree = relevant == bool(expect_relevant)
        passed = label_agree and confident
    else:
        passed = relevant and confident

    return {
        "passed": passed,
        "score": round(score, 3),
        "label_agree": label_agree,
        "expect_relevant": expect_relevant,
        "min_score": min_score,
        "verdict": data,
    }
