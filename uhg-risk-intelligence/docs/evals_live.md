# Live LLM evals: `live_query_parser` & `live_overlay_double_rate`

These suites call the **real production functions** (`parse_query`, `extract_overlay_event`) with your `OPENAI_API_KEY`. They do **not** read Phoenix traces. They grade model output against labeled fixtures.

```powershell
python -m evals --live-only
# or together with offline suites:
python -m evals --live
```

Needs: `OPENAI_API_KEY` in `.env` (loaded via `load_project_env()`).

---

## 1. `live_query_parser`

### Purpose

Answer: *When a user asks a natural-language risk question, does the live LLM map it to the right `ScenarioQuery` (segment, drivers, disruptor)?*

That structured object is the contract between the LLM and the deterministic quant core. A wrong segment/disruptor sends the whole pipeline down the wrong path.

### How it runs

```text
fixtures/query_parser.jsonl
        │
        ▼
for each case:
  predicted = parse_query(question)     # real src/ai_steps/query_parser.py
        │
        ├─ ParseFailure? → FAIL (score 0, error=reason)
        │
        └─ ScenarioQuery → score_parser_prediction(..., min_driver_jaccard=0.5)
```

### Fixture shape

Each line in `evals/fixtures/query_parser.jsonl`:

```json
{
  "id": "optum_insight_cyber",
  "question": "How exposed is Optum Insight to cyber risk and data divergence?",
  "expected": {
    "segment": "Optum_Insight",
    "drivers": ["Data_Digital"],
    "disruptor": "D3_tech_data_divergence"
  }
}
```

### Scoring rules

| Field | Rule (live) | Weight in `score` |
|---|---|---|
| **segment** | Must match exactly | 0.4 |
| **disruptor** | Must match exactly | 0.4 |
| **drivers** | Jaccard similarity ≥ **0.5** | 0.2 × jaccard |

\[
\text{score} = 0.4\cdot\mathbb{1}_{seg} + 0.4\cdot\mathbb{1}_{dis} + 0.2\cdot J(drivers)
\]

\[
J = \frac{|pred \cap expected|}{|pred \cup expected|}
\]

**Pass** if segment OK **and** disruptor OK **and** \(J \ge 0.5\).

Why Jaccard ≥ 0.5 (not exact drivers)? Rate/funding questions legitimately map to `Capital`, `Demand`, or both. Exact-only grading caused false fails when the model picked one of two acceptable drivers.

**Example**

| Expected drivers | Predicted | Jaccard | Pass drivers? |
|---|---|---|---|
| `{Capital, Demand}` | `{Demand}` | 0.5 | yes |
| `{Capital, Demand}` | `{Capital, Demand}` | 1.0 | yes |
| `{Data_Digital}` | `{Capital}` | 0.0 | no |
| `{Supply}` | `{Supply}` | 1.0 | yes |

If segment/disruptor wrong → **FAIL** even if score looks middling (e.g. 0.6 from drivers alone is impossible because those weights need both hard fields).

### How to read CLI output

```text
[PASS] live_query_parser: 5/5 (pass_rate=100%, mean_score=0.940)
  (ok) optum_health_ma_rate score=0.900
  (ok) optum_insight_cyber score=1.000
```

- `(ok)` / `(X)` = case passed / failed the pass rule  
- `score` = continuous quality (useful when many cases pass but drivers are soft)  
- `ParseFailure` / API errors → `(X)` with `error=...`

Inspect detail via `--json-out evals/last_report.json` → `predicted` vs `expected`, `drivers_jaccard`.

---

## 2. `live_overlay_double_rate`

### Purpose

Answer: *When the strong model extracts an overlay event from news/policy text, are severity / immediacy / persistence calibrated like two human raters (within ±1)?*

Overlay scores are subjective 0–3 judgments. Single-label exact match is too harsh; the project design (and README) intentionally uses **double-rated** ground truth.

### How it runs

```text
fixtures/overlay_double_rate.jsonl
        │
        ▼
for each case:
  event = extract_overlay_event(text, segment, driver)   # real overlay_extractor.py
        │
        ▼
  score_overlay_against_double_raters(predicted, rater_a, rater_b)
```

Only judgment fields are scored: `sign`, `severity_0_to_3`, `immediacy_0_to_3`, `persistence_0_to_3`.  
(Segment/driver are inputs to the extractor, not graded.)

### Fixture shape

```json
{
  "id": "sample_cyber_incident",
  "segment": "Optum_Insight",
  "driver": "Data_Digital",
  "source_text": "A major healthcare technology ... cyber ...",
  "rater_a": {"sign": "risk", "severity_0_to_3": 3, "immediacy_0_to_3": 3, "persistence_0_to_3": 2},
  "rater_b": {"sign": "risk", "severity_0_to_3": 3, "immediacy_0_to_3": 3, "persistence_0_to_3": 2}
}
```

### Scoring rules

For each ordinal field, build an allowed band:

\[
[\max(0,\min(a,b)-1),\; \min(3,\max(a,b)+1)]
\]

Model value must fall inside that band (±1 around the rater range).

Also:

- **sign**: must match **at least one** of rater_a / rater_b  
- **MAE**: mean absolute error vs average of the two raters (reported; not the pass gate alone)

\[
\text{score} = 0.25\cdot\mathbb{1}_{sign} + 0.75\cdot(\text{fraction of ordinal fields in band})
\]

**Pass** if sign OK **and** all three ordinal fields are in band.

**Example** (MA rate notice: raters severity 2 and 3)

| Model severity | Band [1, 3] | OK? |
|---|---|---|
| 2 | yes | yes |
| 3 | yes | yes |
| 1 | yes | yes |
| 0 | no | no |

That matches the product stance: humans disagree by ~1 point; the model should stay in the human envelope, not invent a 0 or a max when raters said ~2–3.

---

## 3. How these help decisions & improvement loops

These evals are a **regression harness for the two LLM judgment steps**, not a substitute for Phoenix path/health evals (`--watch`).

```text
          change prompt / model / schema
                     │
                     ▼
            python -m evals --live-only
                     │
         ┌───────────┴───────────┐
         ▼                       ▼
  parser pass_rate ↓        overlay MAE ↑ / fail
         │                       │
         ▼                       ▼
  inspect failed cases      inspect field-level bands
  (wrong segment/disruptor) (severity too aggressive?)
         │                       │
         ▼                       ▼
  tighten SYSTEM_PROMPT      "prefer lower when uncertain"
  or expand fixture labels   already in overlay prompt
  or adjust Jaccard threshold
         │
         └──────────► re-run --live-only until green
                     then ship / demo with confidence
```

### Concrete decisions they support

| Signal | Decision / action |
|---|---|
| Parser: wrong **segment** often | Prompt examples for segment aliases; enum hints; add fixture cases |
| Parser: wrong **disruptor** | Clarify disruptor definitions in system prompt |
| Parser: low Jaccard on drivers only | Usually OK if ≥0.5; if consistently missing Capital on MA questions, nudge prompt |
| Parser: many `ParseFailure` | Schema/Instructor issues or guardrail `out_of_scope` firing on in-scope wording |
| Overlay: severity always high | Strengthen “rate conservatively” instruction; check strong vs fast model |
| Overlay: fails ±1 band | Either model drift or raters need refresh; don’t tighten to exact match |
| Both green after a model upgrade | Safe to bump `FAST_MODEL` / `STRONG_MODEL` in `.env` |
| Green offline scorers, red `--live` | Logic OK; live LLM behavior regressed |

### What they do **not** decide

- Pathway / risk math quality → quant tests + backtest anchors  
- Guardrail routing / graph completeness → `--watch` / `trace_evals_latest_run`  
- Narrative wording faithfulness → offline `narrative_faithfulness` **or** LLM-as-judge `live_narrative_judge` / `--watch --judge` (see [evals_llm_judge.md](evals_llm_judge.md))

### Suggested cadence

1. **Before a panel/demo or model change:** `python -m evals --live-only`  
2. **Every PR that touches** `query_parser.py`, `overlay_extractor.py`, or their prompts  
3. **Grow fixtures** when you find a real mis-parse in demos — add a jsonl row, don’t only fix the prompt once  
4. Keep **double raters** for overlay; if only one human label exists, don’t pretend exact 0–3 match is fair

---

## Quick comparison vs Phoenix live (`--watch`)

| | `--live` suites | `--watch` / Phoenix |
|---|---|---|
| Calls OpenAI? | Yes, on fixtures | No (reads existing spans) |
| Grades | Content of structured LLM output | Run path / span health |
| Example fail | Segment Optum_Health → Optum_Rx | Missing `generate_narrative` node |
| Improvement lever | Prompt, model, labels | Graph, guardrails, instrumentation |

Use **both**: `--live` for “is the LLM mapping/calibration still right?”, `--watch` for “did this demo run the right pipeline path?”
