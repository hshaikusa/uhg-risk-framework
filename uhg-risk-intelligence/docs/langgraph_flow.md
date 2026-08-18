# LangGraph flow — `src/graph.py`

This diagram matches the **compiled query pipeline** built by `build_graph()` in
`src/graph.py`. Node names are identical to the LangGraph node IDs (visible in
Phoenix traces).

Copy into [mermaid.live](https://mermaid.live) or VS Code Mermaid preview.

## Compiled query graph (used by `demo.py query`)

```mermaid
flowchart TB
    START([__start__]) --> parse_query

    parse_query["parse_query<br/><b>node_parse_query</b><br/>LLM → ScenarioQuery | ParseFailure<br/>+ validate_query guardrails"]

    parse_query --> route_after_parse{route_after_parse}

    route_after_parse -->|clarify<br/>parse_failure set| END_FAIL([END<br/>fail closed])
    route_after_parse -->|check_access| check_access

    check_access["check_access<br/><b>node_check_access</b><br/>enforce_access(role, segment)"]

    check_access --> route_after_access{route_after_access}

    route_after_access -->|denied<br/>access_denied=True| END_DENY([END<br/>fail closed])
    route_after_access -->|compute_baseline| compute_baseline

    compute_baseline["compute_baseline<br/><b>node_compute_baseline</b><br/>deterministic quant core<br/>→ DriverBaseline"]

    compute_baseline --> run_scenario

    run_scenario["run_scenario<br/><b>node_run_scenario</b><br/>scenario engine<br/>→ ScenarioOutput<br/>confidence floor applied"]

    run_scenario --> generate_narrative

    generate_narrative["generate_narrative<br/><b>node_generate_narrative</b><br/>LLM → NarrativeOutput<br/>analyst | executive"]

    generate_narrative --> END_OK([END<br/>scores + narrative])

    classDef llm fill:#e8f4fc,stroke:#007AA7,color:#003366
    classDef det fill:#eef7ee,stroke:#2d6a2d,color:#1a3d1a
    classDef route fill:#fff3e0,stroke:#e65100,color:#bf360c
    classDef terminal fill:#f3e5f5,stroke:#6a1b9a,color:#4a148c

    class parse_query,generate_narrative llm
    class compute_baseline,run_scenario det
    class route_after_parse,route_after_access route
    class END_FAIL,END_DENY,END_OK terminal
```

## `PipelineState` (graph state)

| Field | Set by | Purpose |
|---|---|---|
| `question` | input | Raw NL question |
| `role` | input | Access control role |
| `audience` | input | `analyst` or `executive` narrative |
| `indicator_scores` | input | DataFrame or `list[dict]` for checkpointer |
| `query` | `parse_query` | Validated `ScenarioQuery` |
| `parse_failure` | `parse_query` | Fail-closed parse/guardrail result |
| `access_denied` | `check_access` | Role not allowed for segment |
| `baseline` | `compute_baseline` | Deterministic driver baseline |
| `scenario` | `run_scenario` | Disruptor-adjusted scenario output |
| `narrative` | `generate_narrative` | Final LLM narrative |

## Routing functions

```python
# route_after_parse — after parse_query
parse_failure?  → "clarify"  → END
else            → "check_access"

# route_after_access — after check_access
access_denied?  → "denied"           → END
else            → "compute_baseline"
```

## Optional: persistent memory (`demo.py --thread`)

When `build_graph(checkpointer=SqliteSaver(...))` is used, LangGraph persists
`PipelineState` between invocations on the same `thread_id`. On a follow-up
call, `indicator_scores` may be reused from checkpoint (see `demo.py`).

## Not in the compiled query graph

`node_request_overlay_confirmation` is **defined** in `graph.py` (LangGraph
`interrupt()` for human overlay confirmation) but **not wired** into
`build_graph()` today. The overlay path runs separately via
`demo.py overlay` → `overlay_extractor.py` + `guardrails/gates.py`.

```mermaid
flowchart LR
    subgraph overlay["demo.py overlay (separate from query graph)"]
        SEARCH[Tavily / MCP / bundled] --> EXTRACT[extract_overlay_event LLM]
        EXTRACT --> STAGE[stage_overlay_event STAGED]
        STAGE --> CONFIRM[confirm_overlay_event]
        CONFIRM -->|second confirm| REJECT[invalid_transition guardrail]
    end
```

## Phoenix

With `OBSERVABILITY_BACKEND=phoenix`, each LangGraph node appears as a span
in the Phoenix UI when running `demo.py query`. LLM spans nest under
`parse_query` and `generate_narrative`.
