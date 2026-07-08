# app/graph/review_node.py

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from langgraph.types import interrupt

from app.db.crud import save_human_review, write_audit_log
from app.db.database import SessionLocal
from app.graph.state import AXPlannerState
from app.tools.review_applier import apply_human_review_to_ranking


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_audit(
    state: AXPlannerState,
    node_name: str,
    status: str,
    payload: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return state.get("audit_logs", []) + [
        {
            "node": node_name,
            "status": status,
            "timestamp": utc_now(),
            "payload": payload or {},
        }
    ]


def human_review_node(state: AXPlannerState) -> dict[str, Any]:
    node_name = "human_review"

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
    }

    human_decision = interrupt(review_payload)

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
