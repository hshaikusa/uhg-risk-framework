#!/usr/bin/env python3
"""
End-to-end demo runner.

With a real OPENAI_API_KEY set: runs the actual pipeline, live LLM calls
and all.

Without one: runs the exact same graph with the two LLM steps swapped for
canned responses, so you can see the full control flow — including the
fail-closed paths — with zero setup. This mode is clearly labeled in its
output; it is never presented as a live run.

Usage:
    python demo.py "How exposed is Optum Health to a Medicare Advantage rate cut?"
    python demo.py --role executive "How exposed is Optum Insight to a cyber disruptor?"
"""

from __future__ import annotations

from src.env_loader import load_project_env

load_project_env()

from src.observability import setup_observability
setup_observability()

import argparse
import os
import sys
from datetime import date
from unittest.mock import patch

import numpy as np
import pandas as pd

from src.ai_steps.search_tool import _load_bundled_sample, search_for_overlay_input
from src.guardrails.gates import (
    GuardrailRejection, Role, confirm_overlay_event, stage_overlay_event, validate_query,
)
from src.schemas import (
    Disruptor, Driver, NarrativeAudience, NarrativeOutput, OverlayEvent, OverlaySign,
    ParseFailure, ScenarioOutput, ScenarioQuery, Segment,
)


def sample_indicator_scores(sparse_driver: Driver | None = None) -> pd.DataFrame:
    """Full synthetic coverage across every registered indicator, unless
    sparse_driver is set — then indicators loading on that driver are
    reduced to a single data point, which is the demo path for driving
    coverage/confidence below CONFIDENCE_FLOOR (see --sparse-data).
    """
    from src.quant_core.ontology import INDICATOR_REGISTRY, loading_for
    entities = [s.value for s in Segment]
    rng = np.random.default_rng(11)
    rows = []
    for _, row in INDICATOR_REGISTRY.iterrows():
        ind_id = row["indicator_id"]
        ent_list = entities
        if sparse_driver is not None and loading_for(row, sparse_driver) > 0:
            ent_list = entities[:1]  # simulate a near-total data gap for this driver
        for e in ent_list:
            rows.append(dict(indicator_id=ind_id, entity=e, score_0_100=rng.uniform(20, 80)))
    return pd.DataFrame(rows)

def _mock_parse_query(question: str) -> ScenarioQuery | ParseFailure:
    """Mimics ai_steps.query_parser.parse_query's SHAPE (guess a structured
    query, then run it through the real validate_query guardrail) without a
    network call. This fixes a real bug in the earlier version of this demo:
    it used to patch parse_query to always return a hardcoded ScenarioQuery,
    which meant validate_query — and therefore the retired-segment
    guardrail — could never actually fire in the CLI demo. Now it can,
    because this function calls the exact same validate_query the real
    parse_query calls.
    """
    q = question.lower()
    if "insight" in q or "cyber" in q or ("data" in q and "digital" in q):
        segment, driver, disruptor = Segment.OPTUM_INSIGHT, Driver.DATA_DIGITAL, Disruptor.D3_TECH_DATA_DIVERGENCE
    elif "rx" in q or "pharmacy" in q or "drug pric" in q:
        segment, driver, disruptor = Segment.OPTUM_RX, Driver.CAPITAL, Disruptor.D6_POLITICAL_VOLATILITY
    else:
        segment, driver, disruptor = Segment.OPTUM_HEALTH, Driver.CAPITAL, Disruptor.D6_POLITICAL_VOLATILITY

    candidate = ScenarioQuery(segment=segment, drivers=[driver], disruptor=disruptor, raw_question=question)
    try:
        return validate_query(candidate)  # the real guardrail, not a shortcut
    except GuardrailRejection as e:
        return ParseFailure(reason=e.reason, raw_question=question, suggestion=e.detail)


def _mock_narrative(scenario: ScenarioOutput, aud: NarrativeAudience) -> NarrativeOutput:
    caveat = scenario.below_confidence_floor
    text = (
        f"[MOCK NARRATIVE — set OPENAI_API_KEY for a real generated one] "
        f"{scenario.segment.value} shows final risk {scenario.final_risk} and "
        f"opportunity {scenario.final_opportunity} under {scenario.disruptor.value}."
    )
    if caveat:
        text += " Confidence is below threshold; treat this as directional, not final."
    return NarrativeOutput(audience=aud, text=text, confidence_caveat_shown=caveat, source_scenario=scenario)


def run_pipeline(question: str, role: str, audience: str, thread: str | None,
                  sparse_driver: Driver | None, mcp_context: bool = False) -> None:
    from src.graph import build_graph

    have_key = bool(os.environ.get("OPENAI_API_KEY"))
    if not have_key:
        print("=" * 70)
        print("NO OPENAI_API_KEY DETECTED — LLM steps mocked, everything else is real.")
        print("=" * 70)

    checkpointer, config = None, {}
    if thread:
        from langgraph.checkpoint.sqlite import SqliteSaver
        cm = SqliteSaver.from_conn_string("demo_memory.db")
        checkpointer = cm.__enter__()  # persisted to disk; survives across separate `python demo.py` runs
        config = {"configurable": {"thread_id": thread}}

    patches = [] if have_key else [
        patch("src.graph.parse_query", side_effect=_mock_parse_query),
        patch("src.graph.generate_narrative", side_effect=_mock_narrative),
    ]
    for p in patches:
        p.start()
    try:
        graph = build_graph(checkpointer=checkpointer)

        needs_fresh_data = True
        if checkpointer is not None:
            existing = graph.get_state(config)
            if existing.values and existing.values.get("indicator_scores") is not None:
                needs_fresh_data = False
                print("[MEMORY] Reusing indicator_scores persisted from an earlier call on this thread.")

        input_state = {"question": question, "role": role, "audience": audience}
        if needs_fresh_data:
            fresh_df = sample_indicator_scores(sparse_driver)
            # Records, not a raw DataFrame, whenever a persistent checkpointer
            # is attached — see node_compute_baseline in graph.py for why.
            input_state["indicator_scores"] = fresh_df.to_dict("records") if checkpointer is not None else fresh_df

        state = graph.invoke(input_state, config=config)
    finally:
        for p in patches:
            p.stop()

    if state.get("parse_failure"):
        pf = state["parse_failure"]
        print(f"\n[GUARDRAIL FIRED — query parser, fail-closed]")
        print(f"  reason:     {pf.reason}")
        print(f"  suggestion: {pf.suggestion}")
        return
    if state.get("access_denied"):
        print(f"\n[GUARDRAIL FIRED — access control gate, fail-closed]")
        print(f"  role '{role}' is not permitted to view this segment")
        return

    baseline, scenario = state["baseline"], state["scenario"]
    print(f"\nSegment:    {state['query'].segment.value}")
    print(f"Driver:     {baseline.driver.value}")
    print(f"Disruptor:  {state['query'].disruptor.value}")
    print(f"\n[Deterministic quant core]")
    print(f"  Risk / Opportunity:    {baseline.risk_score} / {baseline.opportunity_score}")
    print(f"  Weighting method:      {baseline.weighting_method}")
    print(f"  Coverage / Confidence: {baseline.coverage} / {baseline.confidence}")
    print(f"\n[Scenario engine]")
    print(f"  Final risk / opportunity: {scenario.final_risk} / {scenario.final_opportunity}")
    if scenario.below_confidence_floor:
        print(f"  [GUARDRAIL FIRED — confidence floor] No pathway recommended "
              f"(confidence {scenario.confidence} < floor)")
    else:
        print(f"  Recommended pathway: {scenario.recommended_pathway.value}")
    print(f"\n[Narrative — {audience}]")
    print(f"  {state['narrative'].text}")

    if mcp_context:
        from src.mcp.enrichment import print_mcp_context
        print_mcp_context()


def run_overlay_demo(segment_name: str, driver_name: str, use_search: bool,
                     use_mcp_search: bool = False) -> None:
    segment, driver = Segment(segment_name), Driver(driver_name)
    have_key = bool(os.environ.get("OPENAI_API_KEY"))

    print("=" * 70)
    print(f"OVERLAY EXTRACTION — segment={segment.value}, driver={driver.value}")
    print("=" * 70)

    if use_mcp_search:
        from src.mcp.enrichment import search_via_mcp_or_fallback
        text, source_label = search_via_mcp_or_fallback(
            query=f"{segment.value} {driver.value} recent regulatory or security event",
            segment_value=segment.value,
        )
    elif use_search:
        text, source_label = search_for_overlay_input(
            query=f"{segment.value} {driver.value} recent regulatory or security event",
            segment_value=segment.value,
        )
    else:
        sample = _load_bundled_sample(segment.value)
        text, source_label = sample["text"], f"bundled_fallback:{sample['id']}"
    print(f"\nInput source: {source_label}")
    print(f"Input text:   {text[:200]}{'...' if len(text) > 200 else ''}")

    if have_key:
        from src.ai_steps.overlay_extractor import extract_overlay_event
        event = extract_overlay_event(text, segment, driver, source_url=source_label)
    else:
        print("\n[MOCKED extraction — set OPENAI_API_KEY for a real one]")
        event = stage_overlay_event(OverlayEvent(
            sign=OverlaySign.RISK, severity_0_to_3=2, immediacy_0_to_3=2, persistence_0_to_3=2,
            sector_relevance_0_to_1=0.8, driver_relevance_0_to_1=0.85, novelty_residual_0_to_1=0.6,
            confidence_0_to_1=0.7, segment=segment, driver=driver, source_text=text,
            source_url=source_label, extracted_by_model="mock", extracted_at=date.today(),
        ))

    print(f"\nExtracted event status: {event.status}  <-- staged, never live, by construction")
    print(f"  severity={event.severity_0_to_3} immediacy={event.immediacy_0_to_3} "
          f"persistence={event.persistence_0_to_3} confidence={event.confidence_0_to_1}")

    print("\n[Simulating analyst confirmation]")
    confirmed = confirm_overlay_event(event, confirmed_by="demo_analyst")
    print(f"  status after confirm_overlay_event(): {confirmed.status}")

    print("\n[GUARDRAIL CHECK — attempting a second confirmation, should be rejected]")
    try:
        confirm_overlay_event(confirmed, confirmed_by="demo_analyst")
        print("  UNEXPECTED: second confirmation succeeded — this would be a bug")
    except GuardrailRejection as e:
        print(f"  [GUARDRAIL FIRED — invalid state transition] {e.reason}: {e.detail}")


def run_tool_call(
    tool_ref: str,
    tool_extra: list[str] | None = None,
    *,
    audience: str = "analyst",
    raw: bool = False,
) -> None:
    from src.mcp.client import call_tool, parse_tool_arguments, parse_tool_ref
    from src.mcp.formatters import print_tool_result

    server, tool = parse_tool_ref(tool_ref)
    arguments = parse_tool_arguments(tool_extra)
    print(f"Calling MCP tool {server}.{tool} ...")
    if arguments:
        print(f"  arguments: {arguments}")
    result = call_tool(server, tool, arguments)
    print()
    print_tool_result(server, tool, result, audience=audience, raw_output=raw)


def run_tool_list() -> None:
    from src.mcp.client import list_all_tools
    tools = list_all_tools()
    if not tools:
        print("No MCP tools available.")
        return
    print("Available MCP tools (server.tool_name):")
    for t in tools:
        desc = f" — {t.description}" if t.description else ""
        print(f"  {t.server}.{t.name}{desc}")


def _guess_segment(question: str) -> Segment:
    q = question.lower()
    if "insight" in q or "cyber" in q or "data" in q:
        return Segment.OPTUM_INSIGHT
    if "rx" in q or "pharmacy" in q or "drug" in q:
        return Segment.OPTUM_RX
    return Segment.OPTUM_HEALTH


def run_without_api_key(question: str, role: str, audience: str) -> None:
    print("=" * 70)
    print("NO OPENAI_API_KEY DETECTED — running with mocked LLM steps.")
    print("This demonstrates the full graph control flow; it is NOT a live run.")
    print("=" * 70)

    segment = _guess_segment(question)
    driver = Driver.DATA_DIGITAL if segment == Segment.OPTUM_INSIGHT else Driver.CAPITAL
    disruptor = Disruptor.D3_TECH_DATA_DIVERGENCE if segment == Segment.OPTUM_INSIGHT \
        else Disruptor.D6_POLITICAL_VOLATILITY

    mock_query = ScenarioQuery(segment=segment, drivers=[driver], disruptor=disruptor, raw_question=question)

    from src.graph import build_graph

    def _mock_narrative(scenario: ScenarioOutput, aud: NarrativeAudience) -> NarrativeOutput:
        caveat = scenario.below_confidence_floor
        text = (
            f"[MOCK NARRATIVE — set OPENAI_API_KEY for a real generated one] "
            f"{scenario.segment.value} shows final risk {scenario.final_risk} and "
            f"opportunity {scenario.final_opportunity} under {scenario.disruptor.value}."
        )
        if caveat:
            text += " Confidence is below threshold; treat this as directional, not final."
        return NarrativeOutput(audience=aud, text=text, confidence_caveat_shown=caveat, source_scenario=scenario)

    with patch("src.graph.parse_query", return_value=mock_query), \
         patch("src.graph.generate_narrative", side_effect=_mock_narrative):
        graph = build_graph()
        state = graph.invoke({
            "question": question, "role": role, "audience": audience,
            "indicator_scores": sample_indicator_scores(),
        })

    if state.get("parse_failure"):
        print(f"\nParse failure (fail-closed): {state['parse_failure']}")
        return
    if state.get("access_denied"):
        print(f"\nAccess denied (fail-closed) for role={role}, segment={segment.value}")
        return

    baseline = state["baseline"]
    scenario = state["scenario"]
    print(f"\nSegment:    {segment.value}")
    print(f"Driver:     {driver.value}")
    print(f"Disruptor:  {disruptor.value}")
    print(f"\n[Deterministic quant core — real computation, no mocking]")
    print(f"  Risk score:        {baseline.risk_score}")
    print(f"  Opportunity score: {baseline.opportunity_score}")
    print(f"  Weighting method:  {baseline.weighting_method}")
    print(f"  Coverage:          {baseline.coverage}")
    print(f"  Confidence:        {baseline.confidence}")
    print(f"\n[Scenario engine — real computation, no mocking]")
    print(f"  Final risk:         {scenario.final_risk}")
    print(f"  Final opportunity:  {scenario.final_opportunity}")
    print(f"  Below confidence floor: {scenario.below_confidence_floor}")
    print(f"  Recommended pathway: {scenario.recommended_pathway}")
    print(f"\n[Narrative — MOCKED, real run would call the {audience}-facing LLM prompt]")
    print(f"  {state['narrative'].text}")
    print(f"  (set OPENAI_API_KEY to see a real generated narrative instead)")


def run_with_api_key(question: str, role: str, audience: str) -> None:
    from src.graph import build_graph
    graph = build_graph()
    state = graph.invoke({
        "question": question, "role": role, "audience": audience,
        "indicator_scores": sample_indicator_scores(),
    })

    if state.get("parse_failure"):
        print(f"Parse failure (fail-closed): {state['parse_failure']}")
        return
    if state.get("access_denied"):
        print(f"Access denied (fail-closed).")
        return

    print(f"Segment: {state['query'].segment.value}")
    print(f"Baseline: {state['baseline']}")
    print(f"Scenario: {state['scenario']}")
    print(f"\nNarrative ({audience}):\n{state['narrative'].text}")

def _flush_traces() -> None:
    from src.observability import flush_traces
    flush_traces()

if __name__ == "__main__":
    import sys
    # Backward-compatible shim: the original command shape was
    # `python demo.py "question"` with no subcommand. Preserve that by
    # defaulting to the `query` subcommand when the first arg isn't a known
    # subcommand or -h/--help.
    if len(sys.argv) > 1 and sys.argv[1] not in ("query", "overlay", "tool", "-h", "--help"):
        sys.argv.insert(1, "query")

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)

    p_query = sub.add_parser("query", help="Ask a scenario question through the full pipeline")
    p_query.add_argument("question")
    p_query.add_argument("--role", default=Role.ANALYST,
                          choices=[Role.ANALYST, Role.EXECUTIVE, Role.ADMIN, Role.GUEST])
    p_query.add_argument("--audience", default="analyst", choices=["analyst", "executive"])
    p_query.add_argument("--thread", default=None, help="Session/thread id for persistent memory across calls")
    p_query.add_argument("--sparse-data", default=None, choices=[d.value for d in Driver],
                          help="Simulate a coverage gap on this driver to trigger the confidence-floor guardrail")
    p_query.add_argument("--mcp-context", action="store_true",
                          help="After a successful run, fetch supplemental context via MCP (non-authoritative)")

    p_overlay = sub.add_parser("overlay", help="Run the overlay-extraction path")
    p_overlay.add_argument("--segment", required=True, choices=[s.value for s in Segment])
    p_overlay.add_argument("--driver", required=True, choices=[d.value for d in Driver])
    p_overlay.add_argument("--live-search", action="store_true",
                            help="Use Tavily live search instead of the bundled fallback text")
    p_overlay.add_argument("--mcp-search", action="store_true",
                            help="Try MCP search tools first, then fall back to Tavily/bundled data")

    p_tool = sub.add_parser("tool", help="List or call optional MCP tools (supplemental data)")
    tool_sub = p_tool.add_subparsers(dest="tool_cmd", required=True)
    tool_sub.add_parser("list", help="List tools from configured MCP servers")
    p_call = tool_sub.add_parser(
        "call",
        help="Call server.tool_name; pass args as --arg key=value or --key value",
    )
    p_call.add_argument("tool_ref", help="MCP tool as server.tool_name (e.g. local.list_schema)")
    p_call.add_argument("--audience", default="analyst", choices=["analyst", "executive"],
                        help="Readable summary detail level (default: analyst)")
    p_call.add_argument("--raw", action="store_true",
                        help="Print full raw JSON instead of a formatted summary")
    p_call.add_argument("tool_extra", nargs=argparse.REMAINDER,
                        help="Tool args: --arg key=value, --symbol UNH, or symbol=UNH")

    args = parser.parse_args()

    if args.mode == "query":
        sparse = Driver(args.sparse_data) if args.sparse_data else None
        run_pipeline(args.question, args.role, args.audience, args.thread, sparse,
                     mcp_context=args.mcp_context)
    elif args.mode == "overlay":
        run_overlay_demo(args.segment, args.driver, args.live_search, args.mcp_search)
    elif args.mode == "tool":
        if args.tool_cmd == "list":
            run_tool_list()
        elif args.tool_cmd == "call":
            run_tool_call(args.tool_ref, args.tool_extra,
                          audience=args.audience, raw=args.raw)
    _flush_traces()
    