# app/agents/evaluator.py

from __future__ import annotations

from typing import Any

from app.agents.tool_guard import build_tool_permission_report

STATUS_ORDER = {
    "recommended": 6,
    "human_review_required": 5,
    "evidence_insufficient": 4,
    "data_preparation_required": 3,
    "low_roi": 2,
    "excluded": 1,
}
REVIEW_LEVELS = {"enhanced_review", "sensitive_review"}

LOW_EVIDENCE_ISSUE_THRESHOLD = 0.30
ADDITIONAL_EVIDENCE_THRESHOLD = 0.40
POST_REPLAN_ADDITIONAL_EVIDENCE_THRESHOLD = 0.35
CONFIDENCE_THRESHOLD = 0.50
HUMAN_REVIEW_THRESHOLD = 0.65
VERY_WEAK_EVIDENCE_THRESHOLD = 0.15


def clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return round(max(minimum, min(maximum, value)), 3)


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


def build_compliance_map(compliance_assessment: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for item in (compliance_assessment or {}).get("items", []):
        try:
            process_id = int(item.get("process_id") or 0)
        except (TypeError, ValueError):
            continue
        if process_id:
            result[process_id] = item
    return result


def compute_replan_evidence_lift(state: dict[str, Any]) -> float:
    source_collection = (state.get("replan_request") or {}).get("source_collection") or {}
    public_results = ((source_collection.get("public_web_search") or {}).get("results") or [])
    same_domain = source_collection.get("same_domain_discovered") or []
    indexed_chunks = int(source_collection.get("indexed_chunks") or 0)
    public_lift = min(len(public_results), 3) * 0.025
    official_lift = min(len(same_domain), 3) * 0.02
    chunk_lift = min(indexed_chunks, 60) / 60 * 0.055
    return clamp(public_lift + official_lift + chunk_lift, maximum=0.15)


def score_rationale_coverage(candidate: dict[str, Any]) -> float:
    rationale = candidate.get("score_rationale") or {}
    if not isinstance(rationale, dict):
        return 0.0
    required = ["expected_effect", "repeatability", "document_dependency", "data_accessibility", "tech_feasibility", "risk_score"]
    present = [key for key in required if str(rationale.get(key) or "").strip()]
    return clamp(len(present) / len(required))


def score_evidence_coverage(candidate: dict[str, Any], context_count: int, evidence_count: int, replan_evidence_lift: float = 0.0) -> float:
    metadata = candidate.get("discovery_metadata") or {}
    labels = metadata.get("evidence_labels") if isinstance(metadata, dict) else []
    label_score = min(len(labels or []), 3) / 3
    context_score = min(context_count, 4) / 4
    evidence_score = min(evidence_count, 3) / 3
    return clamp(label_score * 0.38 + context_score * 0.34 + evidence_score * 0.28 + replan_evidence_lift)


def score_data_confidence(candidate: dict[str, Any], context_count: int, replan_evidence_lift: float = 0.0) -> float:
    data_accessibility = float(candidate.get("data_accessibility") or 3)
    data_score = clamp(data_accessibility / 5)
    context_score = clamp(min(context_count, 4) / 4)
    return clamp(data_score * 0.66 + context_score * 0.30 + replan_evidence_lift * 0.04)


def score_compliance_alignment(candidate: dict[str, Any]) -> tuple[float, list[str]]:
    issues: list[str] = []
    compliance = candidate.get("compliance") or {}
    status = candidate.get("status")
    if compliance.get("blocked") and status != "excluded":
        issues.append("blocked candidate is not excluded")
    if compliance.get("human_review_required") and status == "recommended":
        issues.append("candidate requires human review")
    if compliance.get("compliance_level") in REVIEW_LEVELS and status == "recommended":
        issues.append("regulated candidate requires review")
    return (0.35, issues) if issues else (1.0, [])


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


def evaluate_candidate(candidate: dict[str, Any], context_count: int, evidence_count: int, replan_evidence_lift: float = 0.0) -> dict[str, Any]:
    evidence_coverage = score_evidence_coverage(candidate, context_count, evidence_count, replan_evidence_lift)
    data_confidence = score_data_confidence(candidate, context_count, replan_evidence_lift)
    rationale_coverage = score_rationale_coverage(candidate)
    compliance_alignment, issues = score_compliance_alignment(candidate)
    risk_uncertainty = score_risk_uncertainty(candidate)
    confidence_score = clamp(
        evidence_coverage * 0.36
        + data_confidence * 0.24
        + rationale_coverage * 0.18
        + compliance_alignment * 0.22
        - risk_uncertainty * 0.12
    )

    if evidence_coverage < LOW_EVIDENCE_ISSUE_THRESHOLD:
        issues.append("low evidence coverage")
    if rationale_coverage < 0.50:
        issues.append("low rationale coverage")
    if data_confidence < 0.50:
        issues.append("low data confidence")

    post_replan = replan_evidence_lift >= 0.08
    additional_evidence_threshold = POST_REPLAN_ADDITIONAL_EVIDENCE_THRESHOLD if post_replan else ADDITIONAL_EVIDENCE_THRESHOLD
    confidence_threshold = CONFIDENCE_THRESHOLD
    human_review_threshold = HUMAN_REVIEW_THRESHOLD
    zero_evidence_coverage = evidence_coverage <= 0.0
    very_weak_evidence_coverage = evidence_coverage < VERY_WEAK_EVIDENCE_THRESHOLD or (evidence_coverage < 0.20 and data_confidence < 0.30)

    return {
        "process_id": candidate.get("process_id"),
        "candidate_agent_name": candidate.get("candidate_agent_name"),
        "confidence_score": confidence_score,
        "evidence_coverage": evidence_coverage,
        "data_confidence": data_confidence,
        "rationale_coverage": rationale_coverage,
        "compliance_alignment": compliance_alignment,
        "risk_uncertainty": risk_uncertainty,
        "replan_evidence_lift": replan_evidence_lift,
        "additional_evidence_threshold": additional_evidence_threshold,
        "confidence_threshold": confidence_threshold,
        "human_review_threshold": human_review_threshold,
        "zero_evidence_coverage": zero_evidence_coverage,
        "very_weak_evidence_coverage": very_weak_evidence_coverage,
        "requires_additional_evidence": zero_evidence_coverage or evidence_coverage < additional_evidence_threshold or confidence_score < confidence_threshold,
        "requires_human_review": confidence_score < human_review_threshold or bool(issues) or candidate.get("status") == "human_review_required",
        "issues": issues,
    }


def apply_evaluation_to_ranking(priority_ranking: dict[str, Any], evaluation_items: list[dict[str, Any]]) -> dict[str, Any]:
    evaluation_map = {int(item["process_id"]): item for item in evaluation_items if item.get("process_id") is not None}
    updated_items: list[dict[str, Any]] = []

    for candidate in priority_ranking.get("items", []):
        copied = dict(candidate)
        process_id = int(copied.get("process_id") or 0)
        evaluation = evaluation_map.get(process_id)
        if evaluation:
            copied["agent_evaluation"] = evaluation
            compliance = copied.get("compliance") or {}
            compliance_review_required = compliance.get("compliance_level") in REVIEW_LEVELS or bool(compliance.get("human_review_required"))
            if compliance.get("blocked"):
                copied["status"] = "excluded"
            elif copied.get("status") == "recommended" and compliance_review_required:
                copied["status"] = "human_review_required"
                copied["reason"] = f"{copied.get('reason', '')} Compliance review required.".strip()
            elif copied.get("status") == "recommended" and (evaluation.get("zero_evidence_coverage") or evaluation.get("very_weak_evidence_coverage")):
                copied["status"] = "evidence_insufficient"
                copied["reason"] = f"{copied.get('reason', '')} Evidence coverage is insufficient.".strip()
            elif copied.get("status") == "recommended" and evaluation.get("requires_human_review"):
                copied["status"] = "human_review_required"
                copied["reason"] = f"{copied.get('reason', '')} Agent Evaluator requires Human Review.".strip()
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
        "human_review_required_count": len(review_required),
        "evidence_insufficient_count": len(evidence_insufficient),
        "excluded_count": len(excluded),
        "status_counts": {
            "recommended": len(recommended),
            "human_review_required": len(review_required),
            "evidence_insufficient": len(evidence_insufficient),
            "excluded": len(excluded),
        },
        "top_candidate": updated_items[0] if updated_items else None,
        "agent_evaluator_applied": True,
    }
    return updated


def evaluate_agent_outputs(state: dict[str, Any]) -> dict[str, Any]:
    ranking = state.get("priority_ranking", {}) or {}
    context_map = build_context_count_map(state.get("retrieved_contexts", {}) or {})
    evidence_map = build_evidence_count_map(state.get("evidence_items", []) or [])
    compliance_map = build_compliance_map(
        state.get("compliance_assessment")
        or (state.get("risk_governance", {}) or {}).get("compliance_assessment")
    )
    replan_evidence_lift = compute_replan_evidence_lift(state)
    evaluation_items = []
    ranking_for_evaluation = {**ranking, "items": []}
    for candidate in ranking.get("items", []):
        process_id = int(candidate.get("process_id") or 0)
        enriched_candidate = dict(candidate)
        if not enriched_candidate.get("compliance") and process_id in compliance_map:
            enriched_candidate["compliance"] = compliance_map[process_id]
        ranking_for_evaluation["items"].append(enriched_candidate)
        evaluation_items.append(
            evaluate_candidate(
                candidate=enriched_candidate,
                context_count=context_map.get(process_id, 0),
                evidence_count=evidence_map.get(process_id, 0),
                replan_evidence_lift=replan_evidence_lift,
            )
        )

    updated_ranking = apply_evaluation_to_ranking(ranking_for_evaluation, evaluation_items)
    low_confidence_count = sum(1 for item in evaluation_items if item.get("confidence_score", 1) < CONFIDENCE_THRESHOLD)
    human_review_required_count = sum(1 for item in evaluation_items if item.get("requires_human_review"))
    additional_evidence_count = sum(1 for item in evaluation_items if item.get("requires_additional_evidence"))
    avg_confidence = round(sum(float(item.get("confidence_score") or 0.0) for item in evaluation_items) / len(evaluation_items), 3) if evaluation_items else 0.0
    return {
        "agent_tool_permissions": build_tool_permission_report(),
        "items": evaluation_items,
        "summary": {
            "evaluated_candidates": len(evaluation_items),
            "average_confidence_score": avg_confidence,
            "low_confidence_count": low_confidence_count,
            "human_review_required_count": human_review_required_count,
            "additional_evidence_required_count": additional_evidence_count,
            "replan_evidence_lift": replan_evidence_lift,
            "thresholds": {
                "low_evidence_issue_threshold": LOW_EVIDENCE_ISSUE_THRESHOLD,
                "additional_evidence_threshold": ADDITIONAL_EVIDENCE_THRESHOLD,
                "post_replan_additional_evidence_threshold": POST_REPLAN_ADDITIONAL_EVIDENCE_THRESHOLD,
                "human_review_threshold": HUMAN_REVIEW_THRESHOLD,
                "very_weak_evidence_threshold": VERY_WEAK_EVIDENCE_THRESHOLD,
            },
        },
        "updated_priority_ranking": updated_ranking,
    }
