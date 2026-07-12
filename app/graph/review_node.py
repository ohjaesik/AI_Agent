# app/graph/review_node.py

"""Human Review interrupt/auto approval을 담당하는 node.

Supervisor 최소 승인 정책과 실제 ranking/compliance/evaluation 상태를 보고 사람이 필요한
경우만 interrupt하고, 그렇지 않으면 Supervisor auto approval 기록을 남긴다.
"""

from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from app.core.config import get_settings
from app.db.crud import save_human_review, write_audit_log
from app.db.database import SessionLocal
from app.graph.audit import append_audit
from app.graph.state import AXPlannerState
from app.tools.review_applier import apply_human_review_to_ranking


def priority_status_counts(state: AXPlannerState) -> dict[str, int]:
    """priority_ranking 후보들의 status 분포를 계산해 승인 필요 여부 판단에 사용한다."""
    counts: dict[str, int] = {}
    for item in (state.get("priority_ranking", {}) or {}).get("items", []) or []:
        status = str(item.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def human_approval_need(state: AXPlannerState) -> dict[str, Any]:
    """사람 승인이 정말 필요한지 판단한다.

    Supervisor LLM은 기본적으로 자동 실행을 선호하지만, 아래 조건은 자동으로
    넘기면 안 된다. 이 함수는 최소 승인 원칙을 적용해 필요한 경우에만
    LangGraph interrupt를 발생시키도록 한다.
    """

    settings = get_settings()
    supervisor_policy = state.get("supervisor_approval_policy") or {}
    status_counts = priority_status_counts(state)
    compliance_summary = (state.get("compliance_assessment") or {}).get("summary", {}) or {}
    evaluation_summary = (state.get("agent_evaluation") or {}).get("summary", {}) or {}

    reasons: list[str] = []
    if bool(supervisor_policy.get("requires_human_approval")):
        reasons.append("Supervisor LLM이 현재 단계에 사람 승인이 필요하다고 판단했다.")
    if status_counts.get("human_review_required", 0) > 0:
        reasons.append("후보 중 human_review_required 상태가 있다.")
    if status_counts.get("evidence_insufficient", 0) > 0:
        reasons.append("후보 중 evidence_insufficient 상태가 있어 추가 근거 또는 보류 판단이 필요하다.")
    if int(compliance_summary.get("blocked_count", 0) or 0) > 0:
        reasons.append("규제/거버넌스 screening에서 blocked 후보가 있다.")
    if int(compliance_summary.get("enhanced_review_count", 0) or 0) > 0:
        reasons.append("고영향 가능성 후보가 있어 책임자 검토가 필요하다.")
    if int(compliance_summary.get("sensitive_review_count", 0) or 0) > 0:
        reasons.append("민감정보/기밀정보 가능성 후보가 있어 보안 owner 검토가 필요하다.")
    if int(evaluation_summary.get("additional_evidence_required_count", 0) or 0) > 0:
        reasons.append("Evaluator가 추가 근거 필요 후보를 감지했다.")

    if not settings.supervisor_minimal_human_approval:
        reasons.append("SUPERVISOR_MINIMAL_HUMAN_APPROVAL=false 설정으로 명시적 Human Review를 유지한다.")

    return {
        "required": bool(reasons),
        "reasons": reasons,
        "supervisor_policy": supervisor_policy,
        "status_counts": status_counts,
        "compliance_summary": compliance_summary,
        "evaluation_summary": evaluation_summary,
    }


def build_supervisor_auto_decision(state: AXPlannerState, approval_need: dict[str, Any]) -> dict[str, Any]:
    """Human Review가 필요하지 않은 경우 Supervisor Agent가 자동 승인 기록을 남긴다."""

    return {
        "decision": "approve",
        "reviewer_name": "AX Delivery Supervisor Agent",
        "comment": (
            "Supervisor LLM 최소 승인 정책에 따라 현재 후보군에는 사람 승인 gate가 필요하지 않다고 판단했다. "
            "민감/고영향/근거부족/blocked 신호가 생기면 자동 승인하지 않고 Human Review로 전환한다."
        ),
        "edited_payload": None,
        "review_channel": "supervisor_auto_approval",
        "approval_need": approval_need,
        "supervisor_delegation": state.get("current_supervisor_delegation", {}),
    }


def human_review_node(state: AXPlannerState) -> dict[str, Any]:
    """Human Review interrupt 또는 Supervisor auto approval을 처리한다."""
    node_name = "human_review"

    approval_need = human_approval_need(state)

    review_payload = {
        "message": "AX 도입 우선순위 결과를 검토하고 approve/edit/reject 중 하나를 선택하세요.",
        "allowed_decisions": ["approve", "edit", "reject"],
        "edited_payload_schema": {
            "promote_process_ids": ["process_id"],
            "exclude_process_ids": ["process_id"],
            "status_overrides": {"process_id": "recommended|human_review_required|excluded"},
            "score_overrides": {"process_id": "float score"},
            "reason_overrides": {"process_id": "review reason"},
        },
        "priority_summary": state.get("priority_ranking", {}).get("summary", {}),
        "top_5_candidates": state.get("priority_ranking", {}).get("items", [])[:5],
        "risk_summary": state.get("risk_governance", {}).get("summary", {}),
        "evidence_count": len(state.get("evidence_items", [])),
        "used_source_count": len(state.get("used_sources", [])),
        "approval_need": approval_need,
        "supervisor_delegation": state.get("current_supervisor_delegation", {}),
    }

    if approval_need["required"]:
        human_decision = interrupt(review_payload)
    else:
        human_decision = build_supervisor_auto_decision(state, approval_need)

    if not isinstance(human_decision, dict):
        human_decision = {
            "decision": "reject",
            "reviewer_name": "unknown",
            "comment": "Invalid human review payload.",
            "edited_payload": None,
        }

    decision = human_decision.get("decision", "reject")
    reviewer_name = human_decision.get("reviewer_name", "IT기획팀 담당자")
    comment = human_decision.get("comment")
    edited_payload = human_decision.get("edited_payload")

    reviewed_ranking = apply_human_review_to_ranking(
        priority_ranking=state.get("priority_ranking", {}),
        human_review=human_decision,
    )

    with SessionLocal() as db:
        save_human_review(
            db=db,
            project_id=int(state["project_id"]),
            reviewer_name=reviewer_name,
            decision=decision,
            comment=comment,
            edited_payload=edited_payload,
        )

        write_audit_log(
            db=db,
            project_id=int(state["project_id"]),
            node_name=node_name,
            event_type="completed",
            payload={
                "human_decision": human_decision,
                "review_applied": reviewed_ranking.get("review_applied"),
                "top_candidate": reviewed_ranking.get("summary", {}).get("top_candidate"),
            },
        )

    return {
        "human_review": human_decision,
        "priority_ranking": reviewed_ranking,
        "audit_logs": append_audit(
            state,
            node_name,
            "success",
            payload={
                "decision": decision,
                "reviewer_name": reviewer_name,
                "review_applied": reviewed_ranking.get("review_applied"),
                "top_candidate": reviewed_ranking.get("summary", {}).get("top_candidate", {}).get("candidate_agent_name"),
            },
        ),
    }
