# app/evaluation/agent_quality_eval.py

"""Agent output 품질을 오프라인으로 평가하는 script.

gold case와 workflow result를 비교해 evidence coverage, status calibration, ranking 품질을
점검한다.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

from app.agents.evaluator import evaluate_agent_outputs
from app.evaluation.agent_quality_gold_generator import build_additional_gold_cases

DEFAULT_GOLD_PATH = Path("tests/data/agent_quality_gold.jsonl")
REGRESSION_GOLD_PATH = DEFAULT_GOLD_PATH
BLIND_HOLDOUT_GOLD_PATH = Path("tests/data/blind_holdout_gold.jsonl")
STATUS_LABELS = ["recommended", "human_review_required", "evidence_insufficient", "excluded", "data_preparation_required", "low_roi"]


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Agent 품질 평가용 JSONL case 파일을 dict 목록으로 읽는다."""
    rows = []
    with Path(path).open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_regression_cases(path: str | Path = REGRESSION_GOLD_PATH, include_generated: bool = True) -> list[dict[str, Any]]:
    """회귀 평가용 gold case와 선택적 생성 case를 함께 로드한다."""
    cases = load_jsonl(path)
    if include_generated and Path(path) == REGRESSION_GOLD_PATH:
        cases.extend(build_additional_gold_cases())
    return cases


def load_holdout_cases(path: str | Path = BLIND_HOLDOUT_GOLD_PATH) -> list[dict[str, Any]]:
    """blind holdout 평가용 gold case를 로드한다."""
    return load_jsonl(path)


def load_gold_cases(path: str | Path = DEFAULT_GOLD_PATH, include_generated: bool = True) -> list[dict[str, Any]]:
    # Backward-compatible alias. This is the regression set.
    """기존 호출부 호환을 위해 regression gold case loader를 감싼다."""
    return load_regression_cases(path, include_generated=include_generated)


def load_dataset_cases(dataset: str, include_generated: bool = True) -> tuple[list[dict[str, Any]], str, str]:
    """CLI dataset 옵션에 따라 regression 또는 holdout case 묶음을 선택한다."""
    if dataset == "holdout":
        return load_holdout_cases(), "holdout", str(BLIND_HOLDOUT_GOLD_PATH)
    if dataset == "regression":
        return load_regression_cases(include_generated=include_generated), "regression", str(REGRESSION_GOLD_PATH)
    raise ValueError(f"Unsupported dataset: {dataset}")


def safe_div(numerator: float, denominator: float) -> float:
    """0으로 나누는 metric 계산을 0.0으로 처리한다."""
    return round(numerator / denominator, 4) if denominator else 0.0


def build_state_from_case(case: dict[str, Any]) -> dict[str, Any]:
    """gold case 하나를 실제 evaluator가 소비하는 최소 workflow state로 변환한다."""
    candidate = {
        "process_id": case["process_id"],
        "candidate_agent_name": case["candidate_agent_name"],
        "status": case.get("initial_status", "recommended"),
        "final_score": case.get("final_score", 3.5),
        "saving_rate": case.get("saving_rate", 50.0),
        "risk_score": case.get("risk_score", 3),
        "data_accessibility": case.get("data_accessibility", 3),
        "discovery_metadata": {"evidence_labels": case.get("evidence_labels", [])},
        "score_rationale": case.get("score_rationale", {}),
    }
    if case.get("compliance"):
        candidate["compliance"] = case["compliance"]

    process_key = str(case["process_id"])
    context_count = int(case.get("context_count", 0) or 0)
    evidence_count = int(case.get("evidence_count", 0) or 0)
    evidence_labels = case.get("evidence_labels", []) or []

    state = {
        "priority_ranking": {"items": [candidate], "summary": {"total_candidates": 1}},
        "retrieved_contexts": {process_key: [{"content": f"context {idx}"} for idx in range(context_count)]},
        "evidence_items": [
            {
                "process_id": case["process_id"],
                "citation_label": evidence_labels[idx % len(evidence_labels)] if evidence_labels else None,
                "confidence": 0.85,
            }
            for idx in range(evidence_count)
        ],
        "compliance_assessment": {"items": [case["compliance"]]} if case.get("compliance") else {"items": []},
    }
    if case.get("replan_source_collection"):
        state["replan_request"] = {"source_collection": case["replan_source_collection"]}
    return state


def build_confusion_matrix(expected_values: list[str], predicted_values: list[str]) -> dict[str, dict[str, int]]:
    """expected/predicted label 쌍을 confusion matrix dict로 집계한다."""
    matrix: dict[str, dict[str, int]] = {}
    for expected, predicted in zip(expected_values, predicted_values):
        matrix.setdefault(str(expected), {})
        matrix[str(expected)][str(predicted)] = matrix[str(expected)].get(str(predicted), 0) + 1
    return matrix


def classification_report(expected_values: list[str], predicted_values: list[str], labels: list[str] | None = None) -> dict[str, Any]:
    """status 분류 결과의 precision/recall/f1을 label별, macro, weighted로 계산한다."""
    labels = labels or sorted(set(expected_values) | set(predicted_values))
    per_label: dict[str, dict[str, float]] = {}
    total = len(expected_values)
    weighted_precision_sum = 0.0
    weighted_recall_sum = 0.0
    weighted_f1_sum = 0.0

    for label in labels:
        tp = sum(1 for expected, predicted in zip(expected_values, predicted_values) if expected == label and predicted == label)
        fp = sum(1 for expected, predicted in zip(expected_values, predicted_values) if expected != label and predicted == label)
        fn = sum(1 for expected, predicted in zip(expected_values, predicted_values) if expected == label and predicted != label)
        support = sum(1 for expected in expected_values if expected == label)
        precision = safe_div(tp, tp + fp)
        recall = safe_div(tp, tp + fn)
        f1 = safe_div(2 * precision * recall, precision + recall)
        per_label[label] = {"precision": precision, "recall": recall, "f1": f1, "support": support, "tp": tp, "fp": fp, "fn": fn}
        weighted_precision_sum += precision * support
        weighted_recall_sum += recall * support
        weighted_f1_sum += f1 * support

    active_labels = [label for label in labels if per_label[label]["support"] > 0]
    macro_precision = safe_div(sum(per_label[label]["precision"] for label in active_labels), len(active_labels))
    macro_recall = safe_div(sum(per_label[label]["recall"] for label in active_labels), len(active_labels))
    macro_f1 = safe_div(sum(per_label[label]["f1"] for label in active_labels), len(active_labels))

    return {
        "labels": per_label,
        "macro_avg": {"precision": macro_precision, "recall": macro_recall, "f1": macro_f1},
        "weighted_avg": {
            "precision": safe_div(weighted_precision_sum, total),
            "recall": safe_div(weighted_recall_sum, total),
            "f1": safe_div(weighted_f1_sum, total),
        },
    }


def binary_report(expected_values: list[bool], predicted_values: list[bool]) -> dict[str, Any]:
    """Human Review 필요 여부 같은 이진 예측의 precision/recall/f1을 계산한다."""
    tp = sum(1 for expected, predicted in zip(expected_values, predicted_values) if expected and predicted)
    fp = sum(1 for expected, predicted in zip(expected_values, predicted_values) if not expected and predicted)
    fn = sum(1 for expected, predicted in zip(expected_values, predicted_values) if expected and not predicted)
    tn = sum(1 for expected, predicted in zip(expected_values, predicted_values) if not expected and not predicted)
    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)
    f1 = safe_div(2 * precision * recall, precision + recall)
    return {"precision": precision, "recall": recall, "f1": f1, "tp": tp, "fp": fp, "fn": fn, "tn": tn}


def evaluate_cases(cases: list[dict[str, Any]], evaluation_set: str = "regression", case_source: str | None = None) -> dict[str, Any]:
    """gold case마다 evaluator를 실행해 status/review gate 품질 metric을 산출한다."""
    results = []
    expected_statuses: list[str] = []
    predicted_statuses: list[str] = []
    expected_reviews: list[bool] = []
    predicted_reviews: list[bool] = []

    for case in cases:
        state = build_state_from_case(case)
        result = evaluate_agent_outputs(state)
        candidate = result["updated_priority_ranking"]["items"][0]
        evaluation = candidate.get("agent_evaluation", {})
        predicted_status = str(candidate.get("status"))
        predicted_review = bool(evaluation.get("requires_human_review"))
        expected_status = str(case.get("expected_status"))
        expected_review = bool(case.get("expected_requires_human_review"))

        expected_statuses.append(expected_status)
        predicted_statuses.append(predicted_status)
        expected_reviews.append(expected_review)
        predicted_reviews.append(predicted_review)

        status_ok = predicted_status == expected_status
        review_ok = predicted_review == expected_review
        results.append(
            {
                "evaluation_set": evaluation_set,
                "case_id": case.get("case_id"),
                "candidate_agent_name": case.get("candidate_agent_name"),
                "predicted_status": predicted_status,
                "expected_status": expected_status,
                "status_ok": status_ok,
                "predicted_requires_human_review": predicted_review,
                "expected_requires_human_review": expected_review,
                "review_ok": review_ok,
                "confidence_score": evaluation.get("confidence_score"),
                "evidence_coverage": evaluation.get("evidence_coverage"),
                "data_confidence": evaluation.get("data_confidence"),
                "rationale_coverage": evaluation.get("rationale_coverage"),
                "risk_uncertainty": evaluation.get("risk_uncertainty"),
                "replan_evidence_lift": evaluation.get("replan_evidence_lift"),
                "issues": evaluation.get("issues", []),
            }
        )

    total = len(cases)
    status_correct = sum(1 for expected, predicted in zip(expected_statuses, predicted_statuses) if expected == predicted)
    review_correct = sum(1 for expected, predicted in zip(expected_reviews, predicted_reviews) if expected == predicted)
    status_report = classification_report(expected_statuses, predicted_statuses, labels=STATUS_LABELS)
    review_report = binary_report(expected_reviews, predicted_reviews)

    return {
        "evaluation_set": evaluation_set,
        "case_source": case_source,
        "total_cases": total,
        "status_accuracy": safe_div(status_correct, total),
        "review_gate_accuracy": safe_div(review_correct, total),
        "status_macro_f1": status_report["macro_avg"]["f1"],
        "status_weighted_f1": status_report["weighted_avg"]["f1"],
        "review_gate_f1": review_report["f1"],
        "confusion_matrix": build_confusion_matrix(expected_statuses, predicted_statuses),
        "status_report": status_report,
        "review_gate_report": review_report,
        "misclassified": [item for item in results if not item["status_ok"] or not item["review_ok"]],
        "results": results,
    }


def parse_args() -> argparse.Namespace:
    """CLI 실행 인자를 정의하고 argparse Namespace로 변환한다."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", choices=["regression", "holdout"], default="regression")
    parser.add_argument("--gold-path", type=str, default=None, help="custom JSONL path; bypasses built-in regression/holdout selection")
    parser.add_argument("--no-generated", action="store_true", help="for regression only: use only the seed JSONL file")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--csv", type=str, default=None, help="optional path to save per-case results as CSV")
    parser.add_argument("--markdown", type=str, default=None, help="optional path to save summary metrics as Markdown")
    parser.add_argument("--min-status-accuracy", type=float, default=0.80)
    parser.add_argument("--min-review-accuracy", type=float, default=0.90)
    parser.add_argument("--min-status-macro-f1", type=float, default=0.75)
    parser.add_argument("--min-review-f1", type=float, default=0.90)
    parser.add_argument("--strict", action="store_true", help="exit non-zero when quality gates fail")
    return parser.parse_args()


def quality_gate(metrics: dict[str, Any], min_status_accuracy: float, min_review_accuracy: float, min_status_macro_f1: float = 0.75, min_review_f1: float = 0.90) -> dict[str, Any]:
    """Agent 품질 metric이 회귀/holdout 최소 통과 기준을 만족하는지 판단한다."""
    checks = {
        "status_accuracy": float(metrics.get("status_accuracy", 0.0)) >= min_status_accuracy,
        "review_gate_accuracy": float(metrics.get("review_gate_accuracy", 0.0)) >= min_review_accuracy,
        "status_macro_f1": float(metrics.get("status_macro_f1", 0.0)) >= min_status_macro_f1,
        "review_gate_f1": float(metrics.get("review_gate_f1", 0.0)) >= min_review_f1,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "min_status_accuracy": min_status_accuracy,
        "min_review_accuracy": min_review_accuracy,
        "min_status_macro_f1": min_status_macro_f1,
        "min_review_f1": min_review_f1,
    }


def save_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    """save_csv 함수. 분석 결과나 사용자 결정을 DB 또는 파일에 저장한다."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "evaluation_set",
        "case_id",
        "candidate_agent_name",
        "expected_status",
        "predicted_status",
        "status_ok",
        "expected_requires_human_review",
        "predicted_requires_human_review",
        "review_ok",
        "confidence_score",
        "evidence_coverage",
        "data_confidence",
        "rationale_coverage",
        "risk_uncertainty",
        "replan_evidence_lift",
    ]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def format_bool(value: bool) -> str:
    """format_bool 함수. 사용자에게 보여줄 문자열이나 보고서 문구로 값을 포맷한다."""
    return "PASS" if value else "FAIL"


def save_markdown(path: str | Path, metrics: dict[str, Any]) -> None:
    """save_markdown 함수. 분석 결과나 사용자 결정을 DB 또는 파일에 저장한다."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    gate = metrics.get("quality_gate", {})
    lines = [
        "# Agent Quality Evaluation Report",
        "",
        "## Summary",
        "",
        f"- evaluation_set: {metrics.get('evaluation_set')}",
        f"- case_source: {metrics.get('case_source')}",
        f"- total_cases: {metrics.get('total_cases')}",
        f"- quality_gate_passed: {gate.get('passed')}",
        f"- status_accuracy: {metrics.get('status_accuracy')}",
        f"- status_macro_f1: {metrics.get('status_macro_f1')}",
        f"- status_weighted_f1: {metrics.get('status_weighted_f1')}",
        f"- review_gate_accuracy: {metrics.get('review_gate_accuracy')}",
        f"- review_gate_f1: {metrics.get('review_gate_f1')}",
        f"- misclassified_count: {len(metrics.get('misclassified', []))}",
        "",
        "## Quality Gate",
        "",
        "| Check | Result |",
        "|---|---:|",
    ]
    for check, passed in (gate.get("checks") or {}).items():
        lines.append(f"| {check} | {format_bool(bool(passed))} |")

    lines.extend(["", "## Status Report", "", "| Status | Precision | Recall | F1 | Support |", "|---|---:|---:|---:|---:|"])
    for label, item in (metrics.get("status_report", {}).get("labels") or {}).items():
        lines.append(f"| {label} | {item.get('precision')} | {item.get('recall')} | {item.get('f1')} | {item.get('support')} |")

    review = metrics.get("review_gate_report", {})
    lines.extend(
        [
            "",
            "## Review Gate Report",
            "",
            "| Precision | Recall | F1 | TP | FP | FN | TN |",
            "|---:|---:|---:|---:|---:|---:|---:|",
            f"| {review.get('precision')} | {review.get('recall')} | {review.get('f1')} | {review.get('tp')} | {review.get('fp')} | {review.get('fn')} | {review.get('tn')} |",
            "",
            "## Misclassified Cases",
            "",
        ]
    )
    if metrics.get("misclassified"):
        lines.extend(["| Case ID | Agent | Expected Status | Predicted Status | Review OK |", "|---|---|---|---|---:|"])
        for item in metrics["misclassified"]:
            lines.append(f"| {item.get('case_id')} | {item.get('candidate_agent_name')} | {item.get('expected_status')} | {item.get('predicted_status')} | {item.get('review_ok')} |")
    else:
        lines.append("No misclassified cases.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    """해당 모듈을 script로 실행했을 때 호출되는 진입점이다."""
    args = parse_args()
    if args.gold_path:
        cases = load_jsonl(args.gold_path)
        evaluation_set = "custom"
        case_source = args.gold_path
    else:
        cases, evaluation_set, case_source = load_dataset_cases(args.dataset, include_generated=not args.no_generated)

    metrics = evaluate_cases(cases, evaluation_set=evaluation_set, case_source=case_source)
    metrics["quality_gate"] = quality_gate(
        metrics,
        min_status_accuracy=args.min_status_accuracy,
        min_review_accuracy=args.min_review_accuracy,
        min_status_macro_f1=args.min_status_macro_f1,
        min_review_f1=args.min_review_f1,
    )
    if args.csv:
        save_csv(args.csv, metrics["results"])
    if args.markdown:
        save_markdown(args.markdown, metrics)
    if args.json:
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
    else:
        print(f"evaluation_set={metrics['evaluation_set']}")
        print(f"total_cases={metrics['total_cases']}")
        print(f"status_accuracy={metrics['status_accuracy']}")
        print(f"status_macro_f1={metrics['status_macro_f1']}")
        print(f"status_weighted_f1={metrics['status_weighted_f1']}")
        print(f"review_gate_accuracy={metrics['review_gate_accuracy']}")
        print(f"review_gate_f1={metrics['review_gate_f1']}")
        print(f"misclassified_count={len(metrics['misclassified'])}")
        print(f"quality_gate_passed={metrics['quality_gate']['passed']}")
    if args.strict and not metrics["quality_gate"]["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
