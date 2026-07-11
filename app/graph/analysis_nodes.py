"""AX 업무 분석/스코어링 계열 LangGraph node.

이 모듈은 `process_analyzer`, `data_readiness`, `automation_feasibility`,
`roi_cost`, `risk_governance`, `priority_ranking`처럼 실제 업무 후보를 분석하고
점수화하는 node를 모아 둔다. DB/RAG context를 불러오는 node와 report/export node는
별도 모듈에 남기고, 여기서는 분석 산출물 생성과 저장/audit 기록에 집중한다.
"""

from __future__ import annotations

from typing import Any

from app.db.crud import save_analysis_result
from app.db.database import SessionLocal
from app.graph.audit import append_audit, append_error
from app.graph.state import AXPlannerState
from app.tools.cost_calculator import calculate_roi_for_processes
from app.tools.risk_checker import check_risks_for_processes
from app.tools.score_calculator import rank_agent_candidates


def process_analyzer_node(state: AXPlannerState) -> dict[str, Any]:
    """업무별 병목, 대상 사용자, 현재 흐름, 근거 요약을 분석한다."""

    node_name = "process_analyzer"

    try:
        items: list[dict[str, Any]] = []

        for process in state.get("business_processes", []):
            process_id = process["id"]
            contexts = state.get("retrieved_contexts", {}).get(str(process_id), [])

            evidence = "RAG 근거 없음"
            citation_label = ""

            if contexts:
                evidence = contexts[0].get("content", "")[:300]

                evidence_items = state.get("evidence_items", [])
                matched_evidence = next(
                    (
                        item
                        for item in evidence_items
                        if item.get("process_id") == process_id
                    ),
                    None,
                )

                if matched_evidence:
                    citation_label = matched_evidence.get("citation_label", "")

            items.append(
                {
                    "process_id": process_id,
                    "process_name": process.get("name"),
                    "target_user": process.get("target_user"),
                    "candidate_agent_name": process.get("candidate_agent_name"),
                    "problem": process.get("problem"),
                    "current_workflow": process.get("current_workflow"),
                    "repeatability": process.get("repeatability", 3),
                    "document_dependency": process.get("document_dependency", 3),
                    "decision_complexity": process.get("decision_complexity", 3),
                    "bottleneck": process.get("problem"),
                    "evidence": evidence,
                    "citation_label": citation_label,
                    "source": "db_process_and_rag_evidence",
                }
            )

        result = {
            "items": items,
            "summary": {
                "total_processes": len(items),
                "high_repeatability_count": sum(
                    1 for item in items if int(item.get("repeatability") or 0) >= 4
                ),
                "high_document_dependency_count": sum(
                    1
                    for item in items
                    if int(item.get("document_dependency") or 0) >= 4
                ),
            },
        }

        with SessionLocal() as db:
            save_analysis_result(
                db=db,
                project_id=int(state["project_id"]),
                node_name=node_name,
                result_json=result,
            )

        return {
            "process_analysis": result,
            "audit_logs": append_audit(
                state,
                node_name,
                "success",
                payload=result.get("summary", {}),
            ),
        }

    except Exception as exc:
        return {
            "errors": append_error(state, node_name, exc),
            "audit_logs": append_audit(state, node_name, "failed"),
        }


def data_readiness_node(state: AXPlannerState) -> dict[str, Any]:
    """업무별 데이터 접근성, 문서 연결성, 준비 필요 여부를 평가한다."""

    node_name = "data_readiness"

    try:
        items: list[dict[str, Any]] = []

        for process in state.get("business_processes", []):
            data_accessibility = int(process.get("data_accessibility") or 3)

            if data_accessibility >= 4:
                readiness_level = "high"
                comment = "문서와 시스템 데이터 접근성이 높아 PoC 착수 가능성이 높다."
            elif data_accessibility == 3:
                readiness_level = "medium"
                comment = "기본 데이터는 있으나 품질 또는 접근권한 확인이 필요하다."
            else:
                readiness_level = "low"
                comment = "데이터 정비 또는 접근권한 확보가 선행되어야 한다."

            items.append(
                {
                    "process_id": process["id"],
                    "process_name": process.get("name"),
                    "data_accessibility": data_accessibility,
                    "readiness_level": readiness_level,
                    "comment": comment,
                }
            )

        result = {
            "items": items,
            "summary": {
                "total_processes": len(items),
                "low_readiness_count": sum(
                    1 for item in items if item["readiness_level"] == "low"
                ),
            },
        }

        with SessionLocal() as db:
            save_analysis_result(
                db=db,
                project_id=int(state["project_id"]),
                node_name=node_name,
                result_json=result,
            )

        return {
            "data_readiness": result,
            "audit_logs": append_audit(
                state,
                node_name,
                "success",
                payload=result.get("summary", {}),
            ),
        }

    except Exception as exc:
        return {
            "errors": append_error(state, node_name, exc),
            "audit_logs": append_audit(state, node_name, "failed"),
        }


def automation_feasibility_node(state: AXPlannerState) -> dict[str, Any]:
    """반복성/효과/구현 가능성/리스크 기반으로 자동화 보조 가능성을 계산한다."""

    node_name = "automation_feasibility"

    try:
        items: list[dict[str, Any]] = []

        for process in state.get("business_processes", []):
            expected_effect = int(process.get("expected_effect") or 3)
            repeatability = int(process.get("repeatability") or 3)
            tech_feasibility = int(process.get("tech_feasibility") or 3)
            risk_score = int(process.get("risk_score") or 3)
            discovery_metadata = process.get("discovery_metadata") or {}
            score_rationale = (
                discovery_metadata.get("score_rationale", {})
                if isinstance(discovery_metadata, dict)
                else {}
            )

            expected_time_reduction_rate = (
                expected_effect * 0.08
                + repeatability * 0.04
                + tech_feasibility * 0.04
                - risk_score * 0.03
            )
            expected_time_reduction_rate = max(
                0.10,
                min(expected_time_reduction_rate, 0.70),
            )

            comment_parts = [
                "기대효과, 반복성, 구현 가능성, 위험도를 기준으로 자동화 보조 효과를 산정했다."
            ]
            if score_rationale.get("tech_feasibility"):
                comment_parts.append(f"구현 근거: {score_rationale.get('tech_feasibility')}")
            if discovery_metadata.get("suitability_rationale"):
                comment_parts.append(f"Discovery 근거: {discovery_metadata.get('suitability_rationale')}")

            items.append(
                {
                    "process_id": process["id"],
                    "process_name": process.get("name"),
                    "candidate_agent_name": process.get("candidate_agent_name"),
                    "automation_type": "recommendation_or_assistive_agent",
                    "tech_feasibility": tech_feasibility,
                    "expected_time_reduction_rate": round(
                        expected_time_reduction_rate,
                        2,
                    ),
                    "comment": " ".join(comment_parts),
                }
            )

        result = {
            "items": items,
            "summary": {
                "total_processes": len(items),
                "high_feasibility_count": sum(
                    1 for item in items if int(item["tech_feasibility"]) >= 4
                ),
            },
        }

        with SessionLocal() as db:
            save_analysis_result(
                db=db,
                project_id=int(state["project_id"]),
                node_name=node_name,
                result_json=result,
            )

        return {
            "automation_feasibility": result,
            "audit_logs": append_audit(
                state,
                node_name,
                "success",
                payload=result.get("summary", {}),
            ),
        }

    except Exception as exc:
        return {
            "errors": append_error(state, node_name, exc),
            "audit_logs": append_audit(state, node_name, "failed"),
        }


def roi_cost_node(state: AXPlannerState) -> dict[str, Any]:
    """업무 후보별 baseline 비용, 예상 절감, PoC 비용을 계산한다."""

    node_name = "roi_cost"

    try:
        result = calculate_roi_for_processes(
            processes=state.get("business_processes", []),
            automation_feasibility=state.get("automation_feasibility"),
        )

        with SessionLocal() as db:
            save_analysis_result(
                db=db,
                project_id=int(state["project_id"]),
                node_name=node_name,
                result_json=result,
            )

        return {
            "roi_cost": result,
            "audit_logs": append_audit(
                state,
                node_name,
                "success",
                payload=result.get("summary", {}),
            ),
        }

    except Exception as exc:
        return {
            "errors": append_error(state, node_name, exc),
            "audit_logs": append_audit(state, node_name, "failed"),
        }


def risk_governance_node(state: AXPlannerState) -> dict[str, Any]:
    """업무 후보의 privacy/security/high-impact risk signal을 탐지한다."""

    node_name = "risk_governance"

    try:
        result = check_risks_for_processes(
            processes=state.get("business_processes", []),
            retrieved_contexts=state.get("retrieved_contexts", {}),
        )

        with SessionLocal() as db:
            save_analysis_result(
                db=db,
                project_id=int(state["project_id"]),
                node_name=node_name,
                result_json=result,
            )

        return {
            "risk_governance": result,
            "audit_logs": append_audit(
                state,
                node_name,
                "success",
                payload=result.get("summary", {}),
            ),
        }

    except Exception as exc:
        return {
            "errors": append_error(state, node_name, exc),
            "audit_logs": append_audit(state, node_name, "failed"),
        }


def priority_ranking_node(state: AXPlannerState) -> dict[str, Any]:
    """ROI, readiness, feasibility, governance를 합쳐 PoC 우선순위를 만든다."""

    node_name = "priority_ranking"

    try:
        result = rank_agent_candidates(
            processes=state.get("business_processes", []),
            roi_cost=state.get("roi_cost"),
            risk_governance=state.get("risk_governance"),
        )

        with SessionLocal() as db:
            save_analysis_result(
                db=db,
                project_id=int(state["project_id"]),
                node_name=node_name,
                result_json=result,
            )

        return {
            "priority_ranking": result,
            "audit_logs": append_audit(
                state,
                node_name,
                "success",
                payload=result.get("summary", {}),
            ),
        }

    except Exception as exc:
        return {
            "errors": append_error(state, node_name, exc),
            "audit_logs": append_audit(state, node_name, "failed"),
        }
