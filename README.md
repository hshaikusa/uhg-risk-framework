# UHG Geopolitical & Regulatory Risk Intelligence — Proof of Concept

A designed-but-unvalidated proof of concept adapting a multi-source
geopolitical risk intelligence framework to UnitedHealth Group. Full design
rationale, pressure-test findings, and the STAR interview narrative live in
`fde-interview-narrative.docx` — this README covers the code: what's real,
what's synthetic, what needs API keys, and how to run demos, observability,
guardrails, and evals.

## Quick start

```bash
# Prefer conda env used for this POC (Windows):
#   conda activate projpro
python -m venv venv && source venv/bin/activate   # or Windows venv equivalent
pip install -r requirements.txt

# Works immediately, no API key — deterministic core + mocked LLM steps:
python demo.py "How exposed is Optum Health to a Medicare Advantage rate cut this year?"

# Unit + offline eval gates (no API key):
PYTHONPATH=. pytest tests/ -v
python -m evals

# Live end-to-end (needs OPENAI_API_KEY):
cp .env.example .env   # fill OPENAI_API_KEY, models, observability
python demo.py query "How exposed is Optum Insight to a cyber disruptor?"
# demo.py / evals auto-load .env from the repo root
```

## Data provenance — read this before presenting any output as real

| Data | Real or synthetic | Source |
|---|---|---|
| Segment revenue figures (`ontology.SEGMENT_REVENUE_USD_B`) | **Real, public** | UnitedHealth Group FY2025 SEC filings / earnings release |
| Backtest anchor events (`data/backtest_anchors.json`) | **Real, public** | UHG earnings disclosures; public reporting on the 2024 Change Healthcare incident |
| Indicator registry & driver loadings (`quant_core/ontology.py`) | **Synthetic, illustrative** | Constructed for this POC — no real CMS/IMD-style feed is wired up yet |
| Sample overlay event texts (`data/sample_overlay_texts.json`) | **Synthetic paraphrase** | Written to represent the real events in `backtest_anchors.json`; not verbatim quotations from any source |
| Expert-elicited weight rationale (`quant_core/weighting.py`) | **Synthetic** | Author's own judgment calls, documented inline — not sourced from any real UHG analyst |

**No proprietary or internal UnitedHealth Group data was used or is required
to run this project.** Nothing here should be presented as reflecting real
UHG internal methodology or data access.

## Architecture (short)

```text
demo.py
  ├─ query  → LangGraph: parse → access → baseline → scenario → narrative
  ├─ overlay → search (optional) → extract → stage → human confirm
  └─ tool   → optional MCP (non-authoritative)

src/quant_core + scenario   → deterministic baseline risk/opportunity
src/ai_steps                → three narrow LLM steps (Instructor)
src/guardrails              → scope, access, confidence floor, overlay staging
src/observability           → Phoenix (default) or LangSmith or none
evals/                      → offline / live / judge / Phoenix path + annotations
```

See [docs/project_flow.md](docs/project_flow.md) and [docs/langgraph_flow.md](docs/langgraph_flow.md).

## What's testable without API keys (and what isn't)

The deterministic quant core, scenario engine, and guardrail logic are pure
Python with no network dependency — `pytest tests/` exercises harmonization,
low-N weighting fallback, confidence-floor behavior, and fail-closed graph
routing. Offline eval suites run with `python -m evals` (fixtures only).

The three LLM steps (`src/ai_steps/`) need `OPENAI_API_KEY` for live calls.
Without a key, guardrails that **wrap** those calls are still tested
(`tests/test_narrative_guardrail.py`, `tests/test_graph_mocked.py`).

Bugs caught during the build (examples):
1. Retired-segment alias matching (`Optum International` vs `Optum_International`) — `guardrails/gates.py`
2. No-API demo path mocked parser but not narrative — fixed in `demo.py`
3. Synthetic indicators only covered Capital — expanded across the registry

## Model tiers

| Step | Model | Why |
|---|---|---|
| Query parsing | `FAST_MODEL` (default `gpt-4o-mini`) | Low-ambiguity structured extraction |
| Narrative generation | `FAST_MODEL` | Templating/rewriting; caveat enforced in code |
| Overlay extraction | `STRONG_MODEL` (default `gpt-4o`) | Severity/immediacy/persistence judgment + mandatory human confirm |
| Eval LLM-as-judge / phoenix.evals | `JUDGE_MODEL` (default `gpt-4.1-mini`) | Dedicated grader, separate from production extractor |

Override via `.env` — see `.env.example`.

## Guardrails

Product gates in `src/guardrails/gates.py` (not prompt-only):

| Gate | Behavior |
|---|---|
| **UHG scope** | Off-topic questions rejected (`out_of_scope`) |
| **Retired segments** | Aliases like Optum International → `unknown_segment` (fail closed) |
| **Access control** | Role × segment (`guest` / analyst / executive / admin) |
| **Confidence floor** | `CONFIDENCE_FLOOR = 0.5` — no pathway if below floor |
| **Narrative caveat** | Low-confidence caveat **appended in code** after the LLM call |
| **Overlay staging** | Every extract enters `staged`; only `confirm_overlay_event` promotes to `confirmed` |

Evals that cover these: offline `scope_gate`, `narrative_caveat_guardrail`, watch paths
`guardrail_clarify` / `access_denied`, plus narrative caveat span checks.
Full mapping: [evals/README.md](evals/README.md#guardrails-product--evals-coverage).

## Observability

Pick **one** backend (do not run Phoenix and LangSmith together for the POC):

| Backend | When |
|---|---|
| **Phoenix** (`OBSERVABILITY_BACKEND=phoenix`) | Local, open source; default for this repo |
| **LangSmith** | Hosted; needs `LANGSMITH_API_KEY` |
| **none** | Offline/tests |

### Phoenix setup

```env
OBSERVABILITY_BACKEND=phoenix
PHOENIX_PROJECT=uhg-risk-intelligence
PHOENIX_COLLECTOR_ENDPOINT=http://127.0.0.1:6006/v1/traces
```

```powershell
phoenix serve   # UI http://127.0.0.1:6006
```

- Spans export via `src/observability.py` (OTLP).
- Local store defaults to `~/.phoenix/phoenix.db` (WAL files while running).
- **Select project `uhg-risk-intelligence` in the UI** — not `default`.
- MCP calls emit `mcp.call_tool` / `mcp.list_tools`; overlay `--live-search` emits `tavily.search` (RETRIEVER).

`demo.py` only **exports** traces. Eval **annotations** require `python -m evals ... --annotate`.

| UI location | Use |
|---|---|
| Traces → span → **Annotations** | `eval.*` (CODE), `phoenix_eval.*` / judges (LLM) |
| **Evaluators** page (“connect database”) | Not used by this repo for local serve |

## Evals

Harness: [evals/README.md](evals/README.md). Deeper docs under `docs/evals_*.md`.

```powershell
python -m evals                         # offline fixtures + sample spans
python -m evals --live-only             # parser + overlay + all judges (OpenAI)
python -m evals --judges-only           # LLM-as-judge fixtures only
python -m evals --phoenix-only --annotate
python -m evals --phoenix-only --phoenix-evals --annotate
python -m evals --watch --interval 10 --phoenix-evals --annotate
python -m evals --watch --judge --phoenix-evals --annotate
python -m evals --all --annotate --json-out evals/last_report.json

pytest tests/test_evals_offline.py tests/test_llm_judge_rules.py `
  tests/test_phoenix_evals_dataframe.py tests/test_run_path_classifier.py
```

| Layer | Examples |
|---|---|
| Offline | Scope gate, parser smoke, overlay ±1, narrative faithfulness/caveat, retrieval keywords, backtest anchors, sample Phoenix spans |
| Live fixtures | Real `parse_query` (exact + Jaccard drivers), live overlay double-rate |
| Custom judges | Narrative faithfulness/style, retrieval relevance, overlay calibration (`JUDGE_MODEL`) |
| Phoenix path | Per-run `full_success` / `overlay_success` / `guardrail_clarify` / `mcp_tool` / … |
| Phoenix-native | Arize `phoenix.evals` classifiers on latest-run payloads (`--phoenix-evals`) |

**Continuous demo loop:** Terminal A `phoenix serve` · Terminal B `python -m evals --watch --phoenix-evals --annotate` · Terminal C `demo.py query|overlay|tool …`

CLI markers: `(ok)` pass · `(X)` fail · `(-)` skipped N/A.

## Optional MCP tools (supplemental data)

Non-authoritative context only; main pipeline unchanged.

```bash
python demo.py tool list
python demo.py tool call local.list_schema
python demo.py tool call local.get_backtest_anchors
python demo.py tool call yfmcp.yfinance_get_ticker_info --symbol UNH
python demo.py query "How exposed is Optum Insight to cyber risk?" --mcp-context
python demo.py overlay --segment Optum_Insight --driver Data_Digital --mcp-search
```

`MCP_ENABLED=true` by default. Copy `mcp_servers.json.example` → `mcp_servers.json` for optional servers (e.g. `yfmcp` via `uvx yfmcp`).

## Demo CLI (common)

```bash
python demo.py query "How exposed is Optum Health to a Medicare Advantage rate cut this year?" --role analyst --audience analyst
python demo.py query "How is NVIDIA stock doing?" --role guest          # expect clarify / out_of_scope
python demo.py overlay --segment Optum_Insight --driver Data_Digital --live-search
python demo.py tool call local.get_backtest_anchors
```

## Project layout

```
src/
  schemas.py                 # data contracts — read first
  quant_core/                # deterministic ontology, harmonize, weight, baseline
  scenario/engine.py         # disruptor × sector × segment, pathways
  guardrails/gates.py        # scope, access, confidence floor, overlay stage/confirm
  ai_steps/                  # query_parser, narrative_generator, overlay_extractor, search
  observability.py           # phoenix | langsmith | none
  data/                      # backtest anchors + synthetic samples
  graph.py                   # LangGraph orchestration only
tests/                       # unit tests + offline gates (no API key)
evals/                       # fixtures, scorers, judges, phoenix_evals, watch, runner
  README.md                  # full evals + observability + guardrail coverage map
demo.py                      # CLI entry (query | overlay | tool)
docs/
  langgraph_flow.md
  project_flow.md
  evals_live.md
  evals_llm_judge.md
  evals_phoenix_native.md
  emerging_events_rag_design.md   # design-only RAG for S&P/IMD + emerging events
```

## Design notes (not implemented)

[docs/emerging_events_rag_design.md](docs/emerging_events_rag_design.md) — plan for storing emerging news/reports in a RAG store between S&P/IMD score cycles, hybrid retrieval, and metrics (nDCG, faithfulness, etc.). Illustrative samples only.

## Known limitations

See `fde-interview-narrative.docx` Section 6 for the full list (data sourcing,
low-N weighting, Community & State scoping, etc.). This code implements that
section's design decisions rather than restating them here.
