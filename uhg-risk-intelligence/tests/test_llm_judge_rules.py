"""Unit tests for LLM-judge pass rules (no API calls)."""

from evals.judges.narrative import (
    NarrativeFaithfulnessVerdict,
    NarrativeStyleVerdict,
    score_narrative_faithfulness_verdict,
    score_narrative_style_verdict,
)
from evals.judges.overlay import OverlayJudgeVerdict, score_overlay_judge_verdict
from evals.judges.retrieval import RetrievalJudgeVerdict, score_retrieval_judge_verdict


def test_faithfulness_pass_bar_and_label_agree():
    good = NarrativeFaithfulnessVerdict(
        faithful=True,
        unsupported_claims=[],
        risk_numbers_ok=True,
        pathway_ok=True,
        score=0.9,
        rationale="ok",
    )
    scored = score_narrative_faithfulness_verdict(good, expect_faithful=True)
    assert scored["passed"] is True

    scored_mismatch = score_narrative_faithfulness_verdict(good, expect_faithful=False)
    assert scored_mismatch["passed"] is False
    assert scored_mismatch["label_agree"] is False


def test_faithfulness_bad_fixture_requires_unfaithful_label():
    bad = NarrativeFaithfulnessVerdict(
        faithful=False,
        unsupported_claims=["invented risk 95"],
        risk_numbers_ok=False,
        pathway_ok=False,
        score=0.2,
        rationale="hallucinated",
    )
    scored = score_narrative_faithfulness_verdict(bad, expect_faithful=False)
    assert scored["passed"] is True


def test_style_and_retrieval_and_overlay_rules():
    style = NarrativeStyleVerdict(
        audience_appropriate=True, style_issues=[], score=0.85, rationale="ok"
    )
    assert score_narrative_style_verdict(style, expect_appropriate=True)["passed"]

    ret = RetrievalJudgeVerdict(relevant=False, reasons=["weather"], score=0.95, rationale="no")
    assert score_retrieval_judge_verdict(ret, expect_relevant=False)["passed"]
    assert not score_retrieval_judge_verdict(ret, expect_relevant=True)["passed"]

    overlay = OverlayJudgeVerdict(
        calibrated=True,
        severity_ok=True,
        immediacy_ok=True,
        persistence_ok=True,
        suggested_severity_0_to_3=3,
        score=0.8,
        rationale="ok",
    )
    assert score_overlay_judge_verdict(overlay)["passed"]
    weak = overlay.model_copy(update={"score": 0.5})
    assert not score_overlay_judge_verdict(weak)["passed"]
