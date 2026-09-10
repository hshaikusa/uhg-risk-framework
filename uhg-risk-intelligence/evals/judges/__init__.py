"""LLM-as-judge helpers for live and Phoenix-watch evals.

Uses JUDGE_MODEL (default gpt-4.1-mini) — distinct from FAST_MODEL / STRONG_MODEL.
"""

from evals.judges.narrative import (
    judge_narrative_faithfulness,
    judge_narrative_style,
    score_narrative_faithfulness_verdict,
    score_narrative_style_verdict,
)
from evals.judges.overlay import judge_overlay_calibration, score_overlay_judge_verdict
from evals.judges.retrieval import judge_retrieval_relevance, score_retrieval_judge_verdict

__all__ = [
    "judge_narrative_faithfulness",
    "judge_narrative_style",
    "judge_overlay_calibration",
    "judge_retrieval_relevance",
    "score_narrative_faithfulness_verdict",
    "score_narrative_style_verdict",
    "score_overlay_judge_verdict",
    "score_retrieval_judge_verdict",
]
