# LLM-as-judge evals

Second-model graders (`JUDGE_MODEL`, default `gpt-4.1-mini`) that score open-ended
quality. Distinct from:

- **`--live` label scorers** (`live_query_parser`, `live_overlay_double_rate`) — production LLM + deterministic labels
- **Offline heuristics** (`narrative_faithfulness`, keyword retrieval) — no judge API
- **`--watch` path scorers** — span graph/health without content judging
- **`--phoenix-evals`** — Arize `phoenix.evals` classifiers (same rubrics, UI-native annotations) — see [evals_phoenix_native.md](evals_phoenix_native.md)

## Setup

```env
OPENAI_API_KEY=...
JUDGE_MODEL=gpt-4.1-mini   # dedicated; not FAST_MODEL / STRONG_MODEL
```

Same OpenAI key as the rest of the project.

## Suites

| Suite | Fixtures | What the judge checks |
|---|---|---|
| `live_narrative_judge` | `narrative_judge.jsonl` | Faithfulness vs `ScenarioOutput` (numbers/pathway); includes `mode: generate` live narratives |
| `live_narrative_style_judge` | `narrative_style_judge.jsonl` | Analyst vs executive audience fit |
| `live_retrieval_judge` | `retrieval_relevance.jsonl` | Snippet relevance to segment/driver |
| `live_overlay_judge` | `overlay_double_rate.jsonl` | Soft calibration of live extract ratings (complements ±1 double-rater suite) |
| `trace_llm_judges` | Phoenix spans | Same judges on latest-run narrative / retriever / overlay spans |

### Pass rules

| Judge | Pass |
|---|---|
| Narrative faithfulness | `faithful` + `score ≥ 0.7` + `risk_numbers_ok` + `pathway_ok`; **and** `faithful == expect_faithful` when labeled. Bad fixtures only require `faithful=false`. |
| Style | `audience_appropriate` + `score ≥ 0.7`; label agreement when `expect_appropriate` set |
| Retrieval | judge `relevant == expect_relevant` and confidence `score ≥ 0.7` |
| Overlay | `calibrated` + all ordinal `*_ok` + `score ≥ 0.7` |

## Commands

```powershell
# One-shot everything: offline + live + Phoenix (with judges if Phoenix is up)
python -m evals --all

# All judge fixture suites only
python -m evals --judges-only

# Full live (parser + overlay labels + all judges)
python -m evals --live-only

# Phoenix path + LLM judges on latest run
python -m evals --phoenix-only --judge

# Continuous demo watcher (not part of --all; never exits)
python -m evals --watch --interval 10 --judge --annotate
```

## Retrieval & overlay judge scores

### Retrieval (`judge_retrieval_relevance`)

Judge returns `{relevant: bool, score: 0–1, rationale, reasons}`.

- `score` = **confidence in the relevance call** (not a separate quality scale).
- Online (`--watch --judge`): pass if `relevant=true` **and** `score ≥ 0.7`.
- Fixture suite: pass if `relevant == expect_relevant` **and** `score ≥ 0.7`.

Example from your run: `0.850` → relevant with high confidence → `(ok)`.

### Overlay (`judge_overlay_calibration`)

Judge returns calibration fields for the **proposed** severity/immediacy/persistence:

- `calibrated`, `severity_ok`, `immediacy_ok`, `persistence_ok` (±1 vs judge’s own rating)
- `suggested_severity_0_to_3`, `score` (0–1 calibration quality), `issues`

Pass if **all** of: `calibrated` ∧ all three `*_ok` ∧ `score ≥ 0.7`.

Example: `0.600` → below 0.7 (or a field/`calibrated` failed) → `(X)`. Soft second opinion; double-rater ±1 suite remains the hard label gate.

## Layout

```
evals/judges/
  client.py           # JUDGE_MODEL + Instructor helper
  narrative.py        # faithfulness + style
  retrieval.py
  overlay.py
  phoenix_extract.py  # pull payloads from spans
evals/suites/judge_live.py
evals/suites/judge_phoenix.py
evals/fixtures/narrative_judge.jsonl
evals/fixtures/narrative_style_judge.jsonl
```

## Improvement loop

1. Change narrative / overlay / search prompts or models  
2. `python -m evals --judges-only`  
3. Inspect `--json-out` `verdict.rationale` / `unsupported_claims`  
4. Add failing real examples to jsonl with `expect_*` labels  
5. Optionally `--watch --judge` after demos to catch live drift  

Double-rater overlay suite remains the **primary** severity gate; `live_overlay_judge` is a second opinion for calibration language, not a replacement.
