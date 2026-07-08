# app/evaluation/holdout_candidate_exporter.py

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

EXPORT_FIELDNAMES = [
    "case_id",
    "project_id",
    "company_id",
    "process_id",
    "candidate_agent_name",
    "predicted_status",
    "expected_status",
    "expected_requires_human_review",
    "confidence_score",
    "evidence_coverage",
    "data_confidence",
    "rationale_coverage",
    "risk_uncertainty",
    "replan_evidence_lift",
    "final_score",
    "saving_rate",
    "risk_score",
    "data_accessibility",
    "context_count",
    "evidence_count",
    "evidence_label_count",
    "compliance_level",
    "compliance_blocked",
    "borderline_reason",
]


def build_context_count_map(retrieved_contexts: dict[str, list[dict[str, Any]]]) -> dict[int, int]:
    result: dict[int, int] = {}
    for key, chunks in (retrieved_contexts or {}).items():
        try:
            result[int(key)] = len(chunks or [])
        except (TypeError, ValueError):
            continue
    return result


def build_evidence_count_map(evidence_items: list[dict[str, Any]]) -> dict[int, int]:
    result: dict[int, int] = {}
    for item in evidence_items or []:
        try:
            process_id = int(item.get("process_id"))
        except (TypeError, ValueError):
            continue
        result[process_id] = result.get(process_id, 0) + 1
    return result


def extract_evidence_labels(candidate: dict[str, Any]) -> list[str]:
    metadata = candidate.get("discovery_metadata") or {}
    labels = metadata.get("evidence_labels") if isinstance(metadata, dict) else []
    return [str(label) for label in (labels or [])]


def borderline_reason(candidate: dict[str, Any]) -> str:
    evaluation = candidate.get("agent_evaluation") or {}
    confidence = float(evaluation.get("confidence_score") or 0.0)
    evidence = float(evaluation.get("evidence_coverage") or 0.0)
    data_confidence = float(evaluation.get("data_confidence") or 0.0)
    rationale = float(evaluation.get("rationale_coverage") or 0.0)
    status = str(candidate.get("status") or "")
    compliance = candidate.get("compliance") or {}

    reasons: list[str] = []
    if 0.55 <= confidence <= 0.78:
        reasons.append("confidence_band_0.55_0.78")
    if 0.20 <= evidence <= 0.55:
        reasons.append("mid_evidence_coverage")
    if 0.35 <= data_confidence <= 0.65:
        reasons.append("mid_data_confidence")
    if 0.30 <= rationale <= 0.70:
        reasons.append("partial_rationale")
    if status in {"human_review_required", "evidence_insufficient"}:
        reasons.append("non_recommended_status")
    if compliance and not compliance.get("blocked"):
        reasons.append("compliance_review_boundary")
    return ";".join(reasons)


def is_borderline(candidate: dict[str, Any]) -> bool:
    return bool(borderline_reason(candidate))


def candidate_to_unlabeled_case(
    state: dict[str, Any],
    candidate: dict[str, Any],
    index: int,
    case_id_prefix: str,
    context_map: dict[int, int],
    evidence_map: dict[int, int],
) -> dict[str, Any]:
    process_id = int(candidate.get("process_id") or 0)
    evaluation = candidate.get("agent_evaluation") or {}
    compliance = candidate.get("compliance") or {}
    evidence_labels = extract_evidence_labels(candidate)
    reason = borderline_reason(candidate)

    return {
        "case_id": f"{case_id_prefix}-{index:03d}",
        "project_id": state.get("project_id"),
        "company_id": state.get("company_id"),
        "process_id": process_id,
        "candidate_agent_name": candidate.get("candidate_agent_name"),
        "initial_status": "recommended",
        "predicted_status": candidate.get("status"),
        "expected_status": "",
        "expected_requires_human_review": "",
        "evidence_labels": evidence_labels,
        "context_count": context_map.get(process_id, 0),
        "evidence_count": evidence_map.get(process_id, 0),
        "data_accessibility": candidate.get("data_accessibility", 3),
        "risk_score": candidate.get("risk_score", 3),
        "score_rationale": candidate.get("score_rationale") or {},
        "final_score": candidate.get("final_score"),
        "saving_rate": candidate.get("saving_rate"),
        "confidence_score": evaluation.get("confidence_score"),
        "evidence_coverage": evaluation.get("evidence_coverage"),
        "data_confidence": evaluation.get("data_confidence"),
        "rationale_coverage": evaluation.get("rationale_coverage"),
        "risk_uncertainty": evaluation.get("risk_uncertainty"),
        "replan_evidence_lift": evaluation.get("replan_evidence_lift"),
        "compliance": compliance or None,
        "compliance_level": compliance.get("compliance_level"),
        "compliance_blocked": bool(compliance.get("blocked")),
        "borderline_reason": reason,
        "labeling_note": "Fill expected_status and expected_requires_human_review before using as holdout gold.",
    }


def export_unlabeled_holdout_candidates(
    state: dict[str, Any],
    csv_path: str | Path,
    jsonl_path: str | Path,
    case_id_prefix: str = "graph-holdout",
    borderline_only: bool = False,
    max_cases: int | None = None,
) -> list[dict[str, Any]]:
    candidates = list((state.get("priority_ranking") or {}).get("items") or [])
    if borderline_only:
        candidates = [candidate for candidate in candidates if is_borderline(candidate)]
    if max_cases is not None:
        candidates = candidates[:max_cases]

    context_map = build_context_count_map(state.get("retrieved_contexts", {}) or {})
    evidence_map = build_evidence_count_map(state.get("evidence_items", []) or [])

    rows = [
        candidate_to_unlabeled_case(
            state=state,
            candidate=candidate,
            index=index,
            case_id_prefix=case_id_prefix,
            context_map=context_map,
            evidence_map=evidence_map,
        )
        for index, candidate in enumerate(candidates, start=1)
    ]

    save_unlabeled_csv(csv_path, rows)
    save_unlabeled_jsonl(jsonl_path, rows)
    return rows


def save_unlabeled_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=EXPORT_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in EXPORT_FIELDNAMES})


def save_unlabeled_jsonl(path: str | Path, rows: list[dict[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            payload = {
                "case_id": row["case_id"],
                "process_id": row["process_id"],
                "candidate_agent_name": row["candidate_agent_name"],
                "initial_status": row["initial_status"],
                "evidence_labels": row["evidence_labels"],
                "context_count": row["context_count"],
                "evidence_count": row["evidence_count"],
                "data_accessibility": row["data_accessibility"],
                "risk_score": row["risk_score"],
                "score_rationale": row["score_rationale"],
                "final_score": row["final_score"],
                "saving_rate": row["saving_rate"],
                "compliance": row["compliance"],
                "expected_status": row["expected_status"],
                "expected_requires_human_review": row["expected_requires_human_review"],
                "labeling_note": row["labeling_note"],
            }
            file.write(json.dumps(payload, ensure_ascii=False) + "\n")
