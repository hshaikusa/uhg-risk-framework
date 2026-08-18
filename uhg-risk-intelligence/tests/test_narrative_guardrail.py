"""
Proves the "never hide confidence" guardrail with a MOCKED model client —
no OPENAI_API_KEY, no network call. This is the pattern used throughout:
the guardrail logic that wraps an LLM call is ordinary Python and should be
tested as ordinary Python, independent of whether real credentials are
configured in this environment.
"""
from datetime import date
from unittest.mock import MagicMock, patch

from src.ai_steps.narrative_generator import _RawNarrative, generate_narrative
from src.schemas import Disruptor, Driver, NarrativeAudience, ScenarioOutput, Segment


def _scenario(confidence: float, below_floor: bool) -> ScenarioOutput:
    return ScenarioOutput(
        segment=Segment.OPTUM_HEALTH, disruptor=Disruptor.D6_POLITICAL_VOLATILITY,
        driver=Driver.CAPITAL, final_risk=72.0, final_opportunity=20.0,
        recommended_pathway=None if below_floor else "hold_current_position",
        net_strategic_value=None if below_floor else -5.0,
        confidence=confidence, below_confidence_floor=below_floor,
    )


@patch("src.ai_steps.narrative_generator.get_client")
def test_caveat_forced_in_when_confidence_low(mock_get_client):
    mock_client = MagicMock()
    # Simulate the model writing a clean, caveat-free sentence — exactly the
    # "false confidence" failure mode the guardrail exists to catch.
    mock_client.chat.completions.create.return_value = _RawNarrative(
        text="Optum Health shows elevated capital risk under this scenario."
    )
    mock_get_client.return_value = mock_client

    out = generate_narrative(_scenario(confidence=0.3, below_floor=True), NarrativeAudience.EXECUTIVE)

    assert out.confidence_caveat_shown is True
    assert "below the system's threshold" in out.text
    assert out.text.startswith("Optum Health shows elevated capital risk")


@patch("src.ai_steps.narrative_generator.get_client")
def test_caveat_not_added_when_confidence_healthy(mock_get_client):
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _RawNarrative(
        text="Optum Health shows moderate capital risk under this scenario."
    )
    mock_get_client.return_value = mock_client

    out = generate_narrative(_scenario(confidence=0.85, below_floor=False), NarrativeAudience.ANALYST)

    assert out.confidence_caveat_shown is False
    assert "below the system's threshold" not in out.text


@patch("src.ai_steps.narrative_generator.get_client")
def test_caveat_survives_even_if_model_ignores_the_instruction_not_to_editorialize(mock_get_client):
    """The guardrail must hold even in the adversarial case where the model
    already tried to comment on confidence itself — the deterministic
    append still runs regardless of what's already in the text.
    """
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _RawNarrative(
        text="Optum Health shows high capital risk and we are very confident in this."
    )
    mock_get_client.return_value = mock_client

    out = generate_narrative(_scenario(confidence=0.2, below_floor=True), NarrativeAudience.EXECUTIVE)

    assert out.confidence_caveat_shown is True
    assert "below the system's threshold" in out.text
