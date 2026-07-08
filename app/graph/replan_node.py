# app/graph/replan_node.py

from __future__ import annotations

from typing import Any

from app.agents.tool_guard import assert_tools_allowed
from app.db.crud import save_analysis_result, write_audit_log
from app.db.database import SessionLocal
from app.graph.nodes import append_audit, append_error
from app.graph.state import AXPlannerState


def build_replan_items(state: AXPlannerState) -> list[dict[str, Any]]:
    items = []
    ranking_items = {int(item.get("process_id") or 0): item for item in state.get("priority_ranking", {}).get("items", [])}

    for evaluation in state.get("agent_evaluation", {}).get("items", []):
        if not evaluation.get("requires_additional_evidence"):
            continue
        process_id = int(evaluation.get("process_id") or 0)
        candidate = ranking_items.get(process_id, {})
        items.append(
            {
                "process_id": process_id,
                "candidate_agent_name": evaluation.get("candidate_agent_name") or candidate.get("candidate_agent_name"),
                "process_name": candidate.get("process_name"),
                "evidence_coverage": evaluation.get("evidence_coverage"),
                "confidence_score": evaluation.get("confidence_score"),
                "issues": evaluation.get("issues", []),
                "suggested_actions": [
                    "관련 공식 URL 추가",
                    "업무 매뉴얼 또는 내부 규정 문서 업로드",
                    "해당 업무 owner 인터뷰 메모 추가",
                    "RAG 재색인 후 재평가",
                ],
                "requery_terms": [
                    candidate.get("process_name"),
                    candidate.get("candidate_agent_name"),
                    candidate.get("target_user"),
                    "업무 절차",
                    "규정",
                    "SOP",
                ],
            }
        )
    return items


def should_replan(state: AXPlannerState) -> str:
    attempts = int(state.get("replan_attempts", 0) or 0)
    if attempts >= 1:
        return "human_review"

    evaluation = state.get("agent_evaluation", {}) or {}
    summary = evaluation.get("summary", {}) or {}
    if int(summary.get("additional_evidence_required_count", 0) or 0) > 0:
        return "agent_replan"
    return "human_review"


def agent_replan_node(state: AXPlannerState) -> dict[str, Any]:
    node_name = "agent_replan"

    try:
        assert_tools_allowed(
            "agent_evaluator_agent",
            ["agent evaluator", "evidence coverage scorer", "analysis result writer"],
        )
        attempts = int(state.get("replan_attempts", 0) or 0) + 1
        replan_items = build_replan_items(state)
        replan_request = {
            "attempt": attempts,
            "mode": "rag_requery_and_human_source_request",
            "reason": "Agent Evaluator가 일부 후보의 근거 coverage 또는 confidence 부족을 감지했다.",
            "items": replan_items,
            "note": "현재 graph 내부에서는 기존 RAG 문서 재검색만 수행한다. 새로운 공식 URL 수집이나 문서 업로드는 Human Review/API에서 추가 입력이 필요하다.",
        }

        with SessionLocal() as db:
            save_analysis_result(
                db=db,
                project_id=int(state["project_id"]),
                node_name=node_name,
                result_json=replan_request,
            )
            write_audit_log(
                db=db,
                project_id=int(state["project_id"]),
                node_name=node_name,
                event_type="success",
                payload={"attempt": attempts, "replan_item_count": len(replan_items)},
            )

        return {
            "replan_attempts": attempts,
            "replan_request": replan_request,
            "audit_logs": append_audit(
                state,
                node_name,
                "success",
                payload={"attempt": attempts, "replan_item_count": len(replan_items)},
            ),
        }

    except Exception as exc:
        return {
            "errors": append_error(state, node_name, exc),
            "audit_logs": append_audit(state, node_name, "failed"),
        }
