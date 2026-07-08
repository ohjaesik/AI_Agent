# app/agents/evaluator.py

from __future__ import annotations

from typing import Any

from app.agents.registry import get_agent_registry

STATUS_ORDER = {
    "recommended": 6,
    "human_review_required": 5,
    "evidence_insufficient": 4,
    "data_preparation_required": 3,
    "low_roi": 2,
    "excluded": 1,
}


def clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return round(max(minimum, min(maximum, value)), 3)


def build_context_count_map(retrieved_contexts: dict[str, list[dict[str, Any]]]) -> dict[int, int]:
    result: dict[int, int] = {}
    for key, chunks in (retrieved_contexts or {}).items():
        try:
            process_id = int(key)
        except (TypeError, ValueError):
            continue
        result[process_id] = len(chunks or [])
    return result


def build_evidence_count_map(evidence_items: list[dict[str, Any]]) -> dict[int, int]:
    result: dict[int, int] = {}
    for item in evidence_items or []:
        process_id = item.get("process_id")
        if process_id is None:
            continue
        try:
            parsed = int(process_id)
        except (TypeError, ValueError):
            continue
        result[parsed] = result.get(parsed, 0) + 1
    return result


def score_rationale_coverage(candidate: dict[str, Any]) -> float:
    rationale = candidate.get("score_rationale") or {}
    if not isinstance(rationale, dict):
        return 0.0
    required = [
        "expected_effect",
        "repeatability",
        "document_dependency",
        "data_accessibility",
        "tech_feasibility",
        "risk_score",
    ]
    present = [key for key in required if str(rationale.get(key) or "").strip()]
    return clamp(len(present) / len(required))


def score_evidence_coverage(candidate: dict[str, Any], context_count: int, evidence_count: int) -> float:
    metadata = candidate.get("discovery_metadata") or {}
    labels = metadata.get("evidence_labels") if isinstance(metadata, dict) else []
    label_score = min(len(labels or []), 3) / 3
    context_score = min(context_count, 3) / 3
    evidence_score = min(evidence_count, 2) / 2
    return clamp(label_score * 0.45 + context_score * 0.35 + evidence_score * 0.20)


def score_data_confidence(candidate: dict[str, Any], context_count: int) -> float:
    data_accessibility = float(candidate.get("data_accessibility") or 3)
    data_score = clamp(data_accessibility / 5)
    context_score = clamp(min(context_count, 3) / 3)
    return clamp(data_score * 0.70 + context_score * 0.30)


def score_compliance_alignment(candidate: dict[str, Any]) -> tuple[float, list[str]]:
    issues: list[str] = []
    compliance = candidate.get("compliance") or {}
    status = candidate.get("status")

    if compliance.get("blocked") and status != "excluded":
        issues.append("blocked 후보가 excluded 상태가 아니다.")
    if compliance.get("human_review_required") and status == "recommended":
        issues.append("Human Review 필요 후보가 recommended 상태다.")
    if compliance.get("compliance_level") in {"enhanced_review", "sensitive_review"} and status == "recommended":
        issues.append("강화 검토 후보가 recommended 상태다.")

    if issues:
        return 0.35, issues
    return 1.0, []


def score_risk_uncertainty(candidate: dict[str, Any]) -> float:
    risk_score = float(candidate.get("risk_score") or 3)
    risk_part = clamp((risk_score - 1) / 4)
    compliance = candidate.get("compliance") or {}
    compliance_part = 0.0
    if compliance.get("compliance_level") == "sensitive_review":
        compliance_part = 0.25
    if compliance.get("compliance_level") == "enhanced_review":
        compliance_part = 0.35
    if compliance.get("blocked"):
        compliance_part = 0.60
    return clamp(risk_part * 0.55 + compliance_part * 0.45)


def evaluate_candidate(
    candidate: dict[str, Any],
    context_count: int,
    evidence_count: int,
) -> dict[str, Any]:
    evidence_coverage = score_evidence_coverage(candidate, context_count=context_count, evidence_count=evidence_count)
    data_confidence = score_data_confidence(candidate, context_count=context_count)
    rationale_coverage = score_rationale_coverage(candidate)
    compliance_alignment, issues = score_compliance_alignment(candidate)
    risk_uncertainty = score_risk_uncertainty(candidate)

    confidence_score = clamp(
        evidence_coverage * 0.34
        + data_confidence * 0.24
        + rationale_coverage * 0.18
        + compliance_alignment * 0.24
        - risk_uncertainty * 0.14
    )

    if evidence_coverage < 0.45:
        issues.append("근거 coverage가 낮아 추가 자료 수집이 필요하다.")
    if rationale_coverage < 0.50:
        issues.append("점수 산정 근거가 부족하다.")
    if data_confidence < 0.50:
        issues.append("데이터 접근성 또는 RAG context가 부족하다.")

    requires_additional_evidence = evidence_coverage < 0.60 or confidence_score < 0.50
    requires_human_review = confidence_score < 0.75 or bool(issues) or candidate.get("status") == "human_review_required"

    return {
        "process_id": candidate.get("process_id"),
        "candidate_agent_name": candidate.get("candidate_agent_name"),
        "confidence_score": confidence_score,
        "evidence_coverage": evidence_coverage,
        "data_confidence": data_confidence,
        "rationale_coverage": rationale_coverage,
        "compliance_alignment": compliance_alignment,
        "risk_uncertainty": risk_uncertainty,
        "requires_additional_evidence": requires_additional_evidence,
        "requires_human_review": requires_human_review,
        "issues": issues,
    }


def apply_evaluation_to_ranking(
    priority_ranking: dict[str, Any],
    evaluation_items: list[dict[str, Any]],
) -> dict[str, Any]:
    evaluation_map = {int(item["process_id"]): item for item in evaluation_items if item.get("process_id") is not None}
    updated_items: list[dict[str, Any]] = []

    for candidate in priority_ranking.get("items", []):
        copied = dict(candidate)
        process_id = int(copied.get("process_id") or 0)
        evaluation = evaluation_map.get(process_id)
        if evaluation:
            copied["agent_evaluation"] = evaluation
            if copied.get("status") == "recommended" and evaluation.get("requires_human_review"):
                copied["status"] = "human_review_required"
                copied["reason"] = f"{copied.get('reason', '')} Agent Evaluator 검증 결과 Human Review가 필요하다.".strip()
            if copied.get("status") == "recommended" and evaluation.get("confidence_score", 1.0) < 0.50:
                copied["status"] = "evidence_insufficient"
                copied["reason"] = f"{copied.get('reason', '')} Agent Evaluator 기준 confidence가 낮아 추가 근거가 필요하다.".strip()
            compliance = copied.get("compliance") or {}
            if compliance.get("blocked"):
                copied["status"] = "excluded"
        updated_items.append(copied)

    updated_items.sort(
        key=lambda item: (
            STATUS_ORDER.get(str(item.get("status")), 0),
            float(item.get("final_score") or 0.0),
            float(item.get("saving_rate") or 0.0),
        ),
        reverse=True,
    )
    for rank, item in enumerate(updated_items, start=1):
        item["rank"] = rank

    recommended = [item for item in updated_items if item.get("status") == "recommended"]
    review_required = [item for item in updated_items if item.get("status") == "human_review_required"]
    evidence_insufficient = [item for item in updated_items if item.get("status") == "evidence_insufficient"]
    excluded = [item for item in updated_items if item.get("status") == "excluded"]

    updated = dict(priority_ranking)
    updated["items"] = updated_items
    updated["summary"] = {
        **(priority_ranking.get("summary") or {}),
        "total_candidates": len(updated_items),
        "recommended_count": len(recommended),
        "review_required_count": len(review_required),
        "evidence_insufficient_count": len(evidence_insufficient),
        "excluded_count": len(excluded),
        "top_candidate": updated_items[0] if updated_items else None,
        "agent_evaluator_applied": True,
    }
    return updated


def evaluate_agent_outputs(state: dict[str, Any]) -> dict[str, Any]:
    ranking = state.get("priority_ranking", {}) or {}
    context_map = build_context_count_map(state.get("retrieved_contexts", {}) or {})
    evidence_map = build_evidence_count_map(state.get("evidence_items", []) or [])

    evaluation_items = []
    for candidate in ranking.get("items", []):
        process_id = int(candidate.get("process_id") or 0)
        evaluation_items.append(
            evaluate_candidate(
                candidate=candidate,
                context_count=context_map.get(process_id, 0),
                evidence_count=evidence_map.get(process_id, 0),
            )
        )

    updated_ranking = apply_evaluation_to_ranking(
        priority_ranking=ranking,
        evaluation_items=evaluation_items,
    )

    low_confidence_count = sum(1 for item in evaluation_items if item.get("confidence_score", 1) < 0.50)
    human_review_required_count = sum(1 for item in evaluation_items if item.get("requires_human_review"))
    additional_evidence_count = sum(1 for item in evaluation_items if item.get("requires_additional_evidence"))
    avg_confidence = round(
        sum(float(item.get("confidence_score") or 0.0) for item in evaluation_items) / len(evaluation_items),
        3,
    ) if evaluation_items else 0.0

    return {
        "agent_registry": get_agent_registry(),
        "items": evaluation_items,
        "summary": {
            "evaluated_candidates": len(evaluation_items),
            "average_confidence_score": avg_confidence,
            "low_confidence_count": low_confidence_count,
            "human_review_required_count": human_review_required_count,
            "additional_evidence_required_count": additional_evidence_count,
        },
        "updated_priority_ranking": updated_ranking,
    }
