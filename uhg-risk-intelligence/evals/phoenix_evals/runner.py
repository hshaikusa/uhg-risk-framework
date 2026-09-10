"""Run Arize Phoenix ClassificationEvaluator graders on latest-run spans."""

from __future__ import annotations

import json
import os
from typing import Any

import pandas as pd

from evals.phoenix_evals.dataframe import build_eval_dataframes
from evals.phoenix_evals.templates import (
    NARRATIVE_FAITHFULNESS_TEMPLATE,
    NARRATIVE_STYLE_TEMPLATE,
    OVERLAY_CALIBRATION_TEMPLATE,
    RETRIEVAL_RELEVANCE_TEMPLATE,
)
from evals.types import CaseResult, SuiteReport

# Positive labels that count as pass when score is also high enough.
_PASS_LABELS = {
    "narrative_faithfulness": {"faithful"},
    "narrative_style": {"appropriate"},
    "retrieval_relevance": {"relevant"},
    "overlay_calibration": {"calibrated"},
}


def _judge_model() -> str:
    return os.environ.get("JUDGE_MODEL") or os.environ.get("FAST_MODEL") or "gpt-4.1-mini"


def _require_deps() -> None:
    try:
        from phoenix.evals import LLM, create_classifier, evaluate_dataframe  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "Phoenix evaluators require arize-phoenix with phoenix.evals.\n"
            "  pip install 'arize-phoenix>=4.0'\n"
            f"Original error: {exc}"
        ) from exc
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("Phoenix evaluators require OPENAI_API_KEY")


def build_classifiers(model: str | None = None) -> dict[str, Any]:
    from phoenix.evals import LLM, create_classifier

    llm = LLM(provider="openai", model=model or _judge_model())
    return {
        "narrative_faithfulness": create_classifier(
            name="narrative_faithfulness",
            prompt_template=NARRATIVE_FAITHFULNESS_TEMPLATE,
            llm=llm,
            choices={"faithful": 1.0, "unfaithful": 0.0},
        ),
        "narrative_style": create_classifier(
            name="narrative_style",
            prompt_template=NARRATIVE_STYLE_TEMPLATE,
            llm=llm,
            choices={"appropriate": 1.0, "inappropriate": 0.0},
        ),
        "retrieval_relevance": create_classifier(
            name="retrieval_relevance",
            prompt_template=RETRIEVAL_RELEVANCE_TEMPLATE,
            llm=llm,
            choices={"relevant": 1.0, "irrelevant": 0.0},
        ),
        "overlay_calibration": create_classifier(
            name="overlay_calibration",
            prompt_template=OVERLAY_CALIBRATION_TEMPLATE,
            llm=llm,
            choices={"calibrated": 1.0, "not_calibrated": 0.0},
        ),
    }


def _score_cell_to_dict(cell: Any) -> dict[str, Any]:
    if cell is None or (isinstance(cell, float) and pd.isna(cell)):
        return {}
    if isinstance(cell, dict):
        return cell
    if hasattr(cell, "__dataclass_fields__"):
        return {
            "name": getattr(cell, "name", None),
            "score": getattr(cell, "score", None),
            "label": getattr(cell, "label", None),
            "explanation": getattr(cell, "explanation", None),
        }
    if isinstance(cell, list) and cell:
        return _score_cell_to_dict(cell[0])
    if isinstance(cell, str):
        try:
            parsed = json.loads(cell)
            return _score_cell_to_dict(parsed)
        except json.JSONDecodeError:
            return {"explanation": cell}
    return {"raw": str(cell)}


def _case_from_row(eval_name: str, row: pd.Series) -> CaseResult:
    score_col = f"{eval_name}_score"
    payload = _score_cell_to_dict(row.get(score_col))
    label = str(payload.get("label") or "").lower()
    score_val = payload.get("score")
    try:
        score = float(score_val) if score_val is not None else 0.0
    except (TypeError, ValueError):
        score = 0.0
    pass_labels = _PASS_LABELS.get(eval_name, set())
    passed = label in pass_labels and score >= 0.7
    return CaseResult(
        suite="phoenix_native_evals",
        case_id=f"px_{eval_name}",
        passed=passed,
        score=round(score, 3),
        detail={
            "label": label or None,
            "explanation": payload.get("explanation"),
            "span_id": row.get("span_id"),
            "score_payload": payload,
        },
    )


def _log_annotations(
    results_by_eval: dict[str, pd.DataFrame],
    *,
    base_url: str,
    mirror_span_id: str | None = None,
) -> int:
    from phoenix.client import Client

    client = Client(base_url=base_url)
    rows: list[dict[str, Any]] = []
    for eval_name, df in results_by_eval.items():
        score_col = f"{eval_name}_score"
        for _, row in df.iterrows():
            payload = _score_cell_to_dict(row.get(score_col))
            sid = row.get("span_id") or mirror_span_id
            if not sid:
                continue
            label = payload.get("label")
            score = payload.get("score")
            try:
                score_f = float(score) if score is not None else None
            except (TypeError, ValueError):
                score_f = None
            targets = {str(sid)}
            if mirror_span_id:
                targets.add(str(mirror_span_id))
            for target in targets:
                rows.append(
                    {
                        "span_id": target,
                        "annotation_name": f"phoenix_eval.{eval_name}",
                        "annotator_kind": "LLM",
                        "label": str(label) if label is not None else None,
                        "score": score_f,
                        "explanation": str(payload.get("explanation") or "")[:1500],
                        "metadata": {
                            "source": "phoenix.evals",
                            "evaluator": eval_name,
                            "origin_span_id": str(sid),
                        },
                    }
                )
    if not rows:
        return 0
    ann_df = pd.DataFrame(rows)
    client.spans.log_span_annotations_dataframe(
        dataframe=ann_df,
        annotator_kind="LLM",
        sync=False,
    )
    return len(rows)


def run_phoenix_native_evals(
    spans: list[dict[str, Any]],
    *,
    annotate: bool = False,
    base_url: str | None = None,
    model: str | None = None,
    mirror_span_id: str | None = None,
) -> SuiteReport:
    """Run Phoenix ClassificationEvaluators on extractable payloads from spans."""
    suite = "phoenix_native_evals"
    try:
        _require_deps()
    except Exception as exc:  # noqa: BLE001
        return SuiteReport(
            suite,
            [
                CaseResult(
                    suite=suite,
                    case_id="_setup_error",
                    passed=False,
                    score=0.0,
                    error=str(exc),
                )
            ],
        )

    from phoenix.evals import evaluate_dataframe

    frames = build_eval_dataframes(spans)
    if not frames:
        return SuiteReport(
            suite,
            [
                CaseResult(
                    suite=suite,
                    case_id="_no_payloads",
                    passed=True,
                    score=1.0,
                    detail={
                        "skipped": True,
                        "reason": (
                            "No narrative/retrieval/overlay payloads extractable from spans. "
                            "Query demos need narrative text on generate_narrative/ChatCompletion; "
                            "overlay demos need tavily/extract spans."
                        ),
                    },
                )
            ],
        )

    classifiers = build_classifiers(model=model)
    results: list[CaseResult] = []
    results_by_eval: dict[str, pd.DataFrame] = {}

    for eval_name, df in frames.items():
        evaluator = classifiers[eval_name]
        try:
            out = evaluate_dataframe(dataframe=df, evaluators=[evaluator])
            results_by_eval[eval_name] = out
            for _, row in out.iterrows():
                results.append(_case_from_row(eval_name, row))
        except Exception as exc:  # noqa: BLE001
            results.append(
                CaseResult(
                    suite=suite,
                    case_id=f"px_{eval_name}",
                    passed=False,
                    score=0.0,
                    error=str(exc),
                )
            )

    annotations_logged = 0
    if annotate and results_by_eval:
        url = (
            base_url
            or os.getenv("PHOENIX_BASE_URL")
            or os.getenv("PHOENIX_HOST")
            or "http://127.0.0.1:6006"
        )
        if url.rstrip("/").endswith("/v1/traces"):
            url = url.rstrip("/")[: -len("/v1/traces")] or "http://127.0.0.1:6006"
        try:
            annotations_logged = _log_annotations(
                results_by_eval,
                base_url=url,
                mirror_span_id=mirror_span_id,
            )
            for case in results:
                case.detail = {
                    **(case.detail or {}),
                    "annotations_logged": annotations_logged,
                }
        except Exception as exc:  # noqa: BLE001
            results.append(
                CaseResult(
                    suite=suite,
                    case_id="_annotate_error",
                    passed=False,
                    score=0.0,
                    error=str(exc),
                )
            )

    report = SuiteReport(suite, results)
    # Stash count for watch printer (non-CaseResult side channel via first detail).
    if results and annotations_logged:
        results[0].detail = {
            **(results[0].detail or {}),
            "annotations_logged": annotations_logged,
        }
    return report
