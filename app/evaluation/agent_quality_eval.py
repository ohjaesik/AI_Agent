# app/evaluation/agent_quality_eval.py

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from app.agents.evaluator import evaluate_agent_outputs


DEFAULT_GOLD_PATH = Path("tests/data/agent_quality_gold.jsonl")


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows = []
    with Path(path).open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def build_state_from_case(case: dict[str, Any]) -> dict[str, Any]:
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

    return {
        "priority_ranking": {"items": [candidate], "summary": {"total_candidates": 1}},
        "retrieved_contexts": {process_key: [{"content": f"context {idx}"} for idx in range(context_count)]},
        "evidence_items": [{"process_id": case["process_id"]} for _ in range(evidence_count)],
        "compliance_assessment": {"items": [case["compliance"]]} if case.get("compliance") else {"items": []},
    }


def evaluate_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    results = []
    correct_status = 0
    correct_review = 0
    confusion: dict[str, dict[str, int]] = {}

    for case in cases:
        state = build_state_from_case(case)
        result = evaluate_agent_outputs(state)
        candidate = result["updated_priority_ranking"]["items"][0]
        evaluation = candidate.get("agent_evaluation", {})
        predicted_status = candidate.get("status")
        predicted_review = bool(evaluation.get("requires_human_review"))
        expected_status = case.get("expected_status")
        expected_review = bool(case.get("expected_requires_human_review"))

        confusion.setdefault(str(expected_status), {})
        confusion[str(expected_status)][str(predicted_status)] = confusion[str(expected_status)].get(str(predicted_status), 0) + 1

        status_ok = predicted_status == expected_status
        review_ok = predicted_review == expected_review
        correct_status += int(status_ok)
        correct_review += int(review_ok)
        results.append(
            {
                "case_id": case.get("case_id"),
                "predicted_status": predicted_status,
                "expected_status": expected_status,
                "status_ok": status_ok,
                "predicted_requires_human_review": predicted_review,
                "expected_requires_human_review": expected_review,
                "review_ok": review_ok,
                "confidence_score": evaluation.get("confidence_score"),
                "evidence_coverage": evaluation.get("evidence_coverage"),
                "issues": evaluation.get("issues", []),
            }
        )

    total = len(cases)
    return {
        "total_cases": total,
        "status_accuracy": round(correct_status / total, 4) if total else 0.0,
        "review_gate_accuracy": round(correct_review / total, 4) if total else 0.0,
        "confusion_matrix": confusion,
        "results": results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold-path", type=str, default=str(DEFAULT_GOLD_PATH))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--min-status-accuracy", type=float, default=0.80)
    parser.add_argument("--min-review-accuracy", type=float, default=0.90)
    parser.add_argument("--strict", action="store_true", help="exit non-zero when quality gates fail")
    return parser.parse_args()


def quality_gate(metrics: dict[str, Any], min_status_accuracy: float, min_review_accuracy: float) -> dict[str, Any]:
    passed = (
        float(metrics.get("status_accuracy", 0.0)) >= min_status_accuracy
        and float(metrics.get("review_gate_accuracy", 0.0)) >= min_review_accuracy
    )
    return {
        "passed": passed,
        "min_status_accuracy": min_status_accuracy,
        "min_review_accuracy": min_review_accuracy,
    }


def main() -> None:
    args = parse_args()
    metrics = evaluate_cases(load_jsonl(args.gold_path))
    metrics["quality_gate"] = quality_gate(
        metrics,
        min_status_accuracy=args.min_status_accuracy,
        min_review_accuracy=args.min_review_accuracy,
    )
    if args.json:
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
    else:
        print(f"total_cases={metrics['total_cases']}")
        print(f"status_accuracy={metrics['status_accuracy']}")
        print(f"review_gate_accuracy={metrics['review_gate_accuracy']}")
        print(f"quality_gate_passed={metrics['quality_gate']['passed']}")

    if args.strict and not metrics["quality_gate"]["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
