# Phoenix-native evaluators (`phoenix.evals`)

Use Arize **ClassificationEvaluator** graders on live Phoenix spans — same rubrics
as custom `evals/judges/`, but via the Phoenix evals API with annotations logged
into the UI.

## Prerequisites

```powershell
conda activate projpro
pip install "arize-phoenix>=4.0"   # includes phoenix.evals
```

`.env`:

```env
OPENAI_API_KEY=...
JUDGE_MODEL=gpt-4.1-mini
OBSERVABILITY_BACKEND=phoenix
PHOENIX_PROJECT=uhg-risk-intelligence
PHOENIX_COLLECTOR_ENDPOINT=http://127.0.0.1:6006/v1/traces
```

Terminal A: `phoenix serve`  
Terminal B: run demos so spans exist  

## Commands

```powershell
# One-shot: path scorers + Phoenix native evaluators (+ annotate into UI)
python -m evals --phoenix-only --phoenix-evals --annotate

# Continuous watcher
python -m evals --watch --interval 10 --phoenix-evals --annotate

# Combined with custom LLM judges
python -m evals --watch --judge --phoenix-evals --annotate

# Included in --all (one-shot; not --watch)
python -m evals --all --annotate
```

## What runs

| Evaluator name | When payload exists | Labels (score) |
|---|---|---|
| `narrative_faithfulness` | narrative + scenario extractable | faithful=1 / unfaithful=0 |
| `narrative_style` | same | appropriate=1 / inappropriate=0 |
| `retrieval_relevance` | `tavily.search` / RETRIEVER | relevant=1 / irrelevant=0 |
| `overlay_calibration` | overlay ChatCompletion ratings | calibrated=1 / not_calibrated=0 |

Pass rule (CLI): positive label **and** numeric score ≥ 0.7.

With `--annotate`, results are logged as `phoenix_eval.<name>` span annotations
(`annotator_kind=LLM`) via `log_span_annotations_dataframe`.

## Layout

```
evals/phoenix_evals/
  templates.py    # ClassificationEvaluator prompts (UHG rubrics)
  dataframe.py    # span → eval DataFrames
  runner.py       # create_classifier + evaluate_dataframe + annotate
evals/suites/phoenix_native.py
```

## vs custom judges (`--judge`)

| | `--judge` | `--phoenix-evals` |
|---|---|---|
| Stack | Instructor + `evals/judges/` | `phoenix.evals.create_classifier` |
| Logging | `add_span_annotation` | `log_span_annotations_dataframe` |
| Rubrics | Same intent | Same intent (templates mirrored) |
| UI name prefix | `eval.*` | `phoenix_eval.*` |

Use either or both. Fixture regression (`--judges-only`) stays on custom judges.
