"""
Orchestration layer — this is the piece LangGraph is used for, and only
this piece. Every node below is either a thin wrapper around a deterministic
function (quant core, scenario engine, guardrails) or one of the three
narrow LLM steps. No node does open-ended "agentic" reasoning; the graph's
edges are fixed, not chosen by a model.

The one genuinely dynamic control-flow feature used here is LangGraph's
interrupt-and-resume support, for the overlay-event human-confirmation gate
— the graph pauses, an analyst confirms or rejects out of band, and the
graph resumes. That's a real fit for this library, not a cosmetic one.
"""
from __future__ import annotations

from datetime import date
from typing import Optional, TypedDict

import pandas as pd
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from src.ai_steps.narrative_generator import generate_narrative
from src.ai_steps.query_parser import parse_query
from src.guardrails.gates import GuardrailRejection, enforce_access
from src.quant_core.baseline import compute_driver_baseline
from src.scenario.engine import run_scenario
from src.schemas import (
    DriverBaseline, NarrativeAudience, NarrativeOutput, ParseFailure,
    ScenarioOutput, ScenarioQuery,
)


class PipelineState(TypedDict, total=False):
    question: str
    role: str
    audience: str
    query: Optional[ScenarioQuery]
    parse_failure: Optional[ParseFailure]
    baseline: Optional[DriverBaseline]
    scenario: Optional[ScenarioOutput]
    narrative: Optional[NarrativeOutput]
    access_denied: bool
    indicator_scores: object  # pd.DataFrame in-process, or list[dict] records
                               # when round-tripping through a persisted
                               # checkpointer — see node_compute_baseline


def node_parse_query(state: PipelineState) -> PipelineState:
    result = parse_query(state["question"])
    if isinstance(result, ParseFailure):
        return {**state, "parse_failure": result}
    return {**state, "query": result}


def node_check_access(state: PipelineState) -> PipelineState:
    if state.get("parse_failure") or not state.get("query"):
        return state
    try:
        enforce_access(state["role"], state["query"].segment)
        return {**state, "access_denied": False}
    except GuardrailRejection:
        return {**state, "access_denied": True}


def node_compute_baseline(state: PipelineState) -> PipelineState:
    query: ScenarioQuery = state["query"]
    # Uses whichever driver was requested first — a real deployment would
    # fan this out across all requested drivers; kept to one for clarity here.
    driver = query.drivers[0]

    # indicator_scores travels through graph state as JSON-serializable
    # records (list[dict]), not a raw DataFrame — found live while testing
    # persistent memory: SqliteSaver checkpoints state via msgpack, which
    # can't serialize a DataFrame. Reconstructing it here, at the one node
    # that actually needs DataFrame operations, keeps the rest of the state
    # checkpoint-safe, which is the right constraint for a persisted graph
    # regardless of which checkpointer backend is used.
    raw_scores = state["indicator_scores"]
    scores_df = raw_scores if isinstance(raw_scores, pd.DataFrame) else pd.DataFrame(raw_scores)

    baseline = compute_driver_baseline(
        segment=query.segment, driver=driver,
        indicator_scores=scores_df, as_of=date.today(),
    )
    return {**state, "baseline": baseline}


def node_run_scenario(state: PipelineState) -> PipelineState:
    scenario = run_scenario(state["baseline"], state["query"].disruptor)
    return {**state, "scenario": scenario}


def node_generate_narrative(state: PipelineState) -> PipelineState:
    audience = NarrativeAudience(state.get("audience", "analyst"))
    narrative = generate_narrative(state["scenario"], audience)
    return {**state, "narrative": narrative}


def node_request_overlay_confirmation(state: PipelineState) -> PipelineState:
    """Demonstrates the human-in-the-loop pattern: if an overlay event is
    pending for this segment/driver, the graph pauses here via
    `interrupt()` and waits for an analyst's decision before continuing —
    this is the actual mechanism behind "staged, never live, until
    confirmed," not just a status field nobody enforces.
    """
    pending_event = state.get("pending_overlay_event")
    if not pending_event:
        return state
    decision = interrupt({
        "type": "overlay_confirmation_required",
        "event": pending_event,
        "prompt": "Confirm or reject this extracted overlay event before it can affect any live score.",
    })
    return {**state, "overlay_decision": decision}


def route_after_parse(state: PipelineState) -> str:
    if state.get("parse_failure"):
        return "clarify"
    return "check_access"


def route_after_access(state: PipelineState) -> str:
    return "denied" if state.get("access_denied") else "compute_baseline"


def build_graph(checkpointer=None):
    """checkpointer=None (default) means no cross-invocation memory — every
    .invoke() starts blank, which is what the test suite relies on for
    isolation. Pass a real checkpointer (see demo.py --thread) to get
    session memory: a second .invoke() with the same thread_id resumes from
    where the first one left off, so a follow-up question doesn't need to
    re-specify role/audience/data that were already established.
    """
    graph = StateGraph(PipelineState)
    graph.add_node("parse_query", node_parse_query)
    graph.add_node("check_access", node_check_access)
    graph.add_node("compute_baseline", node_compute_baseline)
    graph.add_node("run_scenario", node_run_scenario)
    graph.add_node("generate_narrative", node_generate_narrative)

    graph.set_entry_point("parse_query")
    graph.add_conditional_edges("parse_query", route_after_parse, {
        "clarify": END,  # fails closed — returns state with parse_failure set
        "check_access": "check_access",
    })
    graph.add_conditional_edges("check_access", route_after_access, {
        "denied": END,  # fails closed — returns state with access_denied=True
        "compute_baseline": "compute_baseline",
    })
    graph.add_edge("compute_baseline", "run_scenario")
    graph.add_edge("run_scenario", "generate_narrative")
    graph.add_edge("generate_narrative", END)
    return graph.compile(checkpointer=checkpointer)

# Flow diagram: docs/langgraph_flow.md
