# Evals

| Mode | Command | Needs |
|---|---|---|
| **Offline** | `python -m evals` | nothing (fixtures) |
| **Online one-shot** | `python -m evals --phoenix-only` | Phoenix + recent traces |
| **Online continuous** | `python -m evals --watch` | Phoenix; re-scores as new traces arrive |
| **One-shot all** | `python -m evals --all` | OpenAI + optional Phoenix |

`--live` / `--judges-only` call OpenAI against labeled fixtures (not Phoenix spans).

Docs:

- **[docs/evals_live.md](../docs/evals_live.md)** — parser/overlay label suites  
- **[docs/evals_llm_judge.md](../docs/evals_llm_judge.md)** — custom Instructor LLM judges  
- **[docs/evals_phoenix_native.md](../docs/evals_phoenix_native.md)** — Arize `phoenix.evals` ClassificationEvaluators  

## Run

```powershell
conda activate projpro
cd C:\Users\Hashim\MachineLearning\uhg-risk-intelligence

# Offline (fixtures + sample spans)
python -m evals

# Online one-shot — path scorers on Phoenix window
python -m evals --phoenix-only
python -m evals --phoenix-only --annotate
python -m evals --phoenix-only --judge
python -m evals --phoenix-only --phoenix-evals --annotate

# Online continuous
python -m evals --watch
python -m evals --watch --interval 10 --annotate --json-out evals/last_report.json
python -m evals --watch --interval 10 --judge --phoenix-evals --annotate
python -m evals --watch --project uhg-risk-intelligence

# LLM fixture suites (OpenAI)
python -m evals --live-only
python -m evals --judges-only

# One-shot everything: offline + live + Phoenix path/judges/phoenix.evals
python -m evals --all
python -m evals --all --annotate --json-out evals/last_report.json

pytest tests/test_evals_offline.py tests/test_llm_judge_rules.py tests/test_phoenix_evals_dataframe.py tests/test_run_path_classifier.py
```

`--all` is the full **one-shot** profile. Continuous demos still use `--watch`
(that loop does not exit, so it is not bundled into `--all`).

### Continuous workflow

1. Terminal A: `phoenix serve` (UI/API on `:6006`)
2. Terminal B: `python -m evals --watch --interval 10 --phoenix-evals --annotate`
3. Terminal C: run `demo.py query ...` / `demo.py tool call ...` / overlay
4. Watcher detects new spans → prints PASS/FAIL → writes annotations
   (path = CODE; phoenix.evals / judges = LLM) visible in the Phoenix UI

Stop the watcher with Ctrl+C.

## Suites

| Suite | Mode | What it checks |
|---|---|---|
| `scope_gate` | offline | UHG scope markers + retired-segment / out_of_scope rejections |
| `parser_scorer_smoke` | offline | Exact-match scorer for `ScenarioQuery` fields |
| `live_query_parser` | `--live` | Real `parse_query`: segment+disruptor exact, drivers Jaccard ≥ 0.5 |
| `live_overlay_double_rate` | `--live` | Real `extract_overlay_event` vs double-rated labels |
| `live_narrative_judge` | `--live` / `--judges-only` | LLM-as-judge narrative faithfulness (+ live generate) |
| `live_narrative_style_judge` | `--live` / `--judges-only` | LLM-as-judge analyst vs executive style |
| `live_retrieval_judge` | `--live` / `--judges-only` | LLM-as-judge retrieval relevance |
| `live_overlay_judge` | `--live` / `--judges-only` | LLM-as-judge overlay calibration (soft; with double-rater) |
| `overlay_double_rate_offline` | offline | ±1 band / MAE scorer vs two raters |
| `narrative_faithfulness` | offline | Numbers/pathway faithfulness + caveat presence |
| `narrative_caveat_guardrail` | offline | Code-enforced low-confidence caveat rule |
| `retrieval_relevance` | offline | Keyword relevance for RETRIEVER-style snippets |
| `backtest_anchors` | offline | Elevated risk directional check for the two real anchors |
| `trace_evals_offline` | offline | Same scorers on sample Phoenix spans fixture |
| `trace_evals_phoenix` | `--phoenix` | Window-level health over recent spans |
| `trace_evals_latest_run` | `--watch` | **Per demo run** path/kinds/guardrail |
| `trace_llm_judges` | `--watch --judge` | Custom LLM judges on latest-run payloads |
| `phoenix_native_evals` | `--phoenix-evals` | Arize `phoenix.evals` classifiers on latest-run payloads |

**Per-run paths** (`run_path`): `full_success` (query), `guardrail_clarify`, `access_denied`,
`partial`, `overlay_success` (overlay/search+extract), `mcp_tool`, or `unknown`.
Span `status_code=UNSET` is normal OpenTelemetry (not an error); only `ERROR` fails `run_error_rate`.

### Trace scorers (observability-backed)

These read span fields Phoenix already shows (`span_kind`, `input.value`,
`output.value`, `tool.name`, status):

- **kind coverage** — LLM/CHAIN present (TOOL/RETRIEVER when available)
- **unknown-kind rate** — OpenInference kind should not be mostly `UNKNOWN`
- **error rate** — span status `ERROR` stays low
- **graph nodes** — `parse_query` … `generate_narrative` when query traces exist
- **guardrail clarify** — `route_after_parse` → `clarify` on out_of_scope
- **retriever** — `tavily.search` has I/O + source/preview
- **MCP tools** — `mcp.call_tool` has `tool.name` + I/O
- **narrative caveat** — low-confidence narrative outputs include the caveat marker

## Layout

```
evals/
  fixtures/          # jsonl datasets + sample_phoenix_spans.json
  judges/            # custom Instructor LLM-as-judge
  phoenix_evals/     # Arize phoenix.evals ClassificationEvaluators
  scorers/           # pure scoring functions (incl. traces.py)
  suites/            # offline.py, live.py, judge_*.py, phoenix_native.py, traces.py
  traces/            # Phoenix fetch + span normalize
  watch.py           # continuous online poller
  runner.py          # CLI
```
