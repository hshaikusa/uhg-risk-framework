"""
Proves the graph's CONTROL FLOW — routing on parse failure, routing on
access denial, the happy path through to a narrative — independent of
whether real model credentials are configured. Both LLM-touching steps
(parse_query, generate_narrative) are mocked; everything downstream of them
(deterministic core, scenario engine, guardrails, graph routing) is real.
"""
from datetime import date
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from src.graph import build_graph
from src.guardrails.gates import Role
from src.schemas import (
    Disruptor, Driver, NarrativeAudience, NarrativeOutput, ParseFailure,
    ScenarioOutput, ScenarioQuery, Segment,
)


def _sample_indicator_scores() -> pd.DataFrame:
    entities = [s.value for s in Segment]
    rng = np.random.default_rng(7)
    rows = [
        dict(indicator_id=ind_id, entity=e, score_0_100=rng.uniform(20, 80))
        for ind_id in ["IND_H01", "IND_H02", "IND_S02"]
        for e in entities
    ]
    return pd.DataFrame(rows)


@patch("src.graph.parse_query")
def test_graph_fails_closed_on_parse_failure(mock_parse):
    mock_parse.return_value = ParseFailure(
        reason="unknown_segment", raw_question="How exposed is Optum International?",
        suggestion="That segment was divested; ask about a current segment.",
    )
    graph = build_graph()
    result = graph.invoke({
        "question": "How exposed is Optum International?", "role": Role.ANALYST,
        "audience": "analyst", "indicator_scores": _sample_indicator_scores(),
    })
    assert result["parse_failure"] is not None
    assert result.get("baseline") is None, "must not proceed to the quant core on a parse failure"
    assert result.get("scenario") is None


@patch("src.graph.parse_query")
def test_graph_fails_closed_on_out_of_scope(mock_parse):
    mock_parse.return_value = ParseFailure(
        reason="out_of_scope",
        raw_question="How is NVIDIA stock doing this year?",
        suggestion="This system answers UHG segment exposure questions only.",
    )
    graph = build_graph()
    result = graph.invoke({
        "question": "How is NVIDIA stock doing this year?",
        "role": Role.ANALYST, "audience": "analyst",
        "indicator_scores": _sample_indicator_scores(),
    })
    assert result["parse_failure"] is not None
    assert result["parse_failure"].reason == "out_of_scope"
    assert result.get("baseline") is None


@patch("src.graph.enforce_access")
@patch("src.graph.parse_query")
def test_graph_fails_closed_on_access_denial(mock_parse, mock_enforce):
    from src.guardrails.gates import GuardrailRejection
    mock_parse.return_value = ScenarioQuery(
        segment=Segment.OPTUM_INSIGHT, drivers=[Driver.DATA_DIGITAL],
        disruptor=Disruptor.D3_TECH_DATA_DIVERGENCE,
        raw_question="How exposed is Optum Insight to a cyber disruptor?",
    )
    mock_enforce.side_effect = GuardrailRejection("access_denied", "not permitted")

    graph = build_graph()
    result = graph.invoke({
        "question": "How exposed is Optum Insight to a cyber disruptor?",
        "role": Role.ANALYST, "audience": "analyst",
        "indicator_scores": _sample_indicator_scores(),
    })
    assert result["access_denied"] is True
    assert result.get("scenario") is None, "must not proceed to the scenario engine when access is denied"


@patch("src.graph.generate_narrative")
@patch("src.graph.parse_query")
def test_graph_happy_path_reaches_narrative(mock_parse, mock_narrative):
    mock_parse.return_value = ScenarioQuery(
        segment=Segment.OPTUM_HEALTH, drivers=[Driver.CAPITAL],
        disruptor=Disruptor.D6_POLITICAL_VOLATILITY,
        raw_question="How exposed is Optum Health to a Medicare Advantage rate cut?",
    )
    mock_narrative.return_value = NarrativeOutput(
        audience=NarrativeAudience.ANALYST, text="Sample narrative.",
        confidence_caveat_shown=False,
        source_scenario=ScenarioOutput(
            segment=Segment.OPTUM_HEALTH, disruptor=Disruptor.D6_POLITICAL_VOLATILITY,
            driver=Driver.CAPITAL, final_risk=70.0, final_opportunity=25.0,
            recommended_pathway="hold_current_position", net_strategic_value=-3.0,
            confidence=0.8, below_confidence_floor=False,
        ),
    )

    graph = build_graph()
    result = graph.invoke({
        "question": "How exposed is Optum Health to a Medicare Advantage rate cut?",
        "role": Role.EXECUTIVE, "audience": "executive",
        "indicator_scores": _sample_indicator_scores(),
    })

    assert result.get("parse_failure") is None
    assert result["baseline"] is not None
    assert result["scenario"] is not None
    assert result["narrative"] is not None
    assert result["narrative"].text == "Sample narrative."
