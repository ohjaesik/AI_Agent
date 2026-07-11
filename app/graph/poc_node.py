# app/graph/poc_node.py

"""승인된 후보를 6주 PoC 계획으로 변환하는 node.

Human Review 결과와 ranking 상태를 보고 MVP Agent, milestone, KPI, exit criteria를 만든다.
"""

from __future__ import annotations

from typing import Any

from app.db.crud import save_analysis_result
from app.db.database import SessionLocal
from app.graph.nodes import append_audit, append_error, build_poc_kpis, build_poc_milestones
from app.graph.state import AXPlannerState


def select_poc_candidate(state: AXPlannerState) -> dict[str, Any] | None:
    """ranking 결과에서 PoC 계획에 사용할 대표 후보를 고른다."""
    ranking_items = state.get("priority_ranking", {}).get("items", [])
    if not ranking_items:
        return None

    review = state.get("human_review", {}) or {}
    edited_payload = review.get("edited_payload") or {}
    promote_ids = edited_payload.get("promote_process_ids") or [] if isinstance(edited_payload, dict) else []
    if promote_ids:
        promoted = next((item for item in ranking_items if item.get("process_id") in promote_ids), None)
        if promoted:
            return promoted

    recommended = [item for item in ranking_items if item.get("status") == "recommended"]
    if recommended:
        return recommended[0]

    if review.get("decision") == "approve":
        reviewable = [
            item for item in ranking_items
            if item.get("status") in {"human_review_required", "evidence_insufficient", "data_preparation_required"}
        ]
        if reviewable:
            return reviewable[0]

    return ranking_items[0]


def poc_delivery_planner_node(state: AXPlannerState) -> dict[str, Any]:
    """검토된 후보를 기반으로 MVP Agent와 PoC milestone/KPI를 생성한다."""
    node_name = "poc_delivery_planner"

    try:
        decision = state.get("human_review", {}).get("decision", "reject")
        first_individual_poc = select_poc_candidate(state)
        agent_name = (first_individual_poc or {}).get("candidate_agent_name") or "AX Delivery Planner"
        process_name = (first_individual_poc or {}).get("process_name") or "최우선 후보 업무"

        result = {
            "mvp_agent": {
                "name": agent_name,
                "type": "assistive_ai_agent",
                "target_process": process_name,
                "description": (
                    f"{process_name}에 대해 공식/내부 문서 근거를 검색하고, "
                    "담당자의 판단을 보조하는 PoC 대상 AI Agent"
                ),
            },
            "human_decision": decision,
            "first_individual_poc_candidate": first_individual_poc,
            "poc_plan": {
                "duration": "6 weeks",
                "milestones": build_poc_milestones(first_individual_poc),
                "entry_criteria": [
                    "대상 업무 owner 지정",
                    "사용 문서 및 접근권한 승인",
                    "PoC 성공 KPI 합의",
                    "Human Review 담당자 지정",
                    "Agent Evaluator confidence 및 근거 coverage 확인",
                ],
                "exit_criteria": [
                    "KPI 목표 달성 여부 확인",
                    "보안/거버넌스 예외 없음 또는 보완계획 수립",
                    "현업 부서의 확대 적용/보류 의견 기록",
                    "Agent Evaluator 검증 결과 및 실패 케이스 기록",
                ],
            },
            "kpis": build_poc_kpis(first_individual_poc),
        }

        with SessionLocal() as db:
            save_analysis_result(
                db=db,
                project_id=int(state["project_id"]),
                node_name=node_name,
                result_json=result,
            )

        return {
            "poc_plan": result,
            "audit_logs": append_audit(
                state,
                node_name,
                "success",
                payload={
                    "human_decision": decision,
                    "mvp_agent": agent_name,
                    "candidate_status": (first_individual_poc or {}).get("status"),
                    "milestone_count": len(result["poc_plan"]["milestones"]),
                },
            ),
        }

    except Exception as exc:
        return {
            "errors": append_error(state, node_name, exc),
            "audit_logs": append_audit(state, node_name, "failed"),
        }
