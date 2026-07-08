# app/graph/nodes.py

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from langgraph.types import interrupt

from app.db.crud import (
    load_project_data,
    save_analysis_result,
    save_human_review,
    write_audit_log,
)
from app.db.database import SessionLocal
from app.graph.state import AXPlannerState
from app.rag.retriever import retrieve_contexts_for_processes
from app.sources.collector import (
    build_used_sources,
    dedupe_evidence,
    internal_document_to_evidence,
    rag_chunk_to_evidence,
)
from app.tools.cost_calculator import calculate_roi_for_processes
from app.tools.report_data_builder import build_report_data
from app.tools.risk_checker import check_risks_for_processes
from app.tools.score_calculator import rank_agent_candidates


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


def append_error(
    state: AXPlannerState,
    node_name: str,
    error: Exception,
) -> list[str]:
    return state.get("errors", []) + [
        f"[{node_name}] {type(error).__name__}: {str(error)}"
    ]


def load_project_data_node(state: AXPlannerState) -> dict[str, Any]:
    node_name = "load_project_data"

    try:
        project_id = int(state["project_id"])
        company_id = int(state["company_id"])

        with SessionLocal() as db:
            payload = load_project_data(
                db=db,
                project_id=project_id,
                company_id=company_id,
            )

            write_audit_log(
                db=db,
                project_id=project_id,
                node_name=node_name,
                event_type="success",
                payload={"company_id": company_id},
            )

        return {
            "project": payload["project"],
            "company_profile": payload["company_profile"],
            "departments": payload["departments"],
            "systems": payload["systems"],
            "business_processes": payload["business_processes"],
            "documents": payload["documents"],
            "audit_logs": append_audit(
                state,
                node_name=node_name,
                status="success",
                payload={
                    "process_count": len(payload["business_processes"]),
                    "document_count": len(payload["documents"]),
                },
            ),
        }

    except Exception as exc:
        return {
            "errors": append_error(state, node_name, exc),
            "audit_logs": append_audit(state, node_name, "failed"),
        }


def retrieve_context_node(state: AXPlannerState) -> dict[str, Any]:
    node_name = "retrieve_context"

    try:
        project_id = int(state["project_id"])
        company_id = int(state["company_id"])
        processes = state.get("business_processes", [])

        with SessionLocal() as db:
            contexts = retrieve_contexts_for_processes(
                db=db,
                processes=processes,
                company_id=company_id,
                top_k=3,
            )

            write_audit_log(
                db=db,
                project_id=project_id,
                node_name=node_name,
                event_type="success",
                payload={
                    "process_count": len(processes),
                    "context_keys": list(contexts.keys()),
                },
            )

        evidence_items: list[dict[str, Any]] = []

        for _, chunks in contexts.items():
            for chunk in chunks:
                evidence_items.append(
                    rag_chunk_to_evidence(
                        chunk,
                        used_for=[
                            "process_analysis",
                            "data_readiness",
                            "risk_governance",
                            "priority_ranking",
                            "report_generation",
                        ],
                    )
                )

        for document in state.get("documents", []):
            evidence_items.append(
                internal_document_to_evidence(
                    document,
                    used_for=[
                        "industry_analysis",
                        "business_process_analysis",
                        "data_readiness",
                        "risk_governance",
                        "report_generation",
                    ],
                )
            )

        evidence_items = dedupe_evidence(evidence_items)
        used_sources = build_used_sources(evidence_items)

        return {
            "retrieved_contexts": contexts,
            "evidence_items": evidence_items,
            "used_sources": used_sources,
            "audit_logs": append_audit(
                state,
                node_name=node_name,
                status="success",
                payload={
                    "context_groups": len(contexts),
                    "evidence_count": len(evidence_items),
                    "used_source_count": len(used_sources),
                },
            ),
        }

    except Exception as exc:
        return {
            "retrieved_contexts": {},
            "evidence_items": [],
            "used_sources": [],
            "errors": append_error(state, node_name, exc),
            "audit_logs": append_audit(state, node_name, "failed"),
        }


def process_analyzer_node(state: AXPlannerState) -> dict[str, Any]:
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
    node_name = "automation_feasibility"

    try:
        items: list[dict[str, Any]] = []

        for process in state.get("business_processes", []):
            expected_effect = int(process.get("expected_effect") or 3)
            repeatability = int(process.get("repeatability") or 3)
            tech_feasibility = int(process.get("tech_feasibility") or 3)
            risk_score = int(process.get("risk_score") or 3)
            discovery_metadata = process.get("discovery_metadata") or {}
            score_rationale = discovery_metadata.get("score_rationale", {}) if isinstance(discovery_metadata, dict) else {}

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


def human_review_node(state: AXPlannerState) -> dict[str, Any]:
    node_name = "human_review"

    review_payload = {
        "message": "AX 도입 우선순위 결과를 검토하고 approve/edit/reject 중 하나를 선택하세요.",
        "allowed_decisions": ["approve", "edit", "reject"],
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
            payload=human_decision,
        )

    return {
        "human_review": human_decision,
        "audit_logs": append_audit(
            state,
            node_name,
            "success",
            payload={"decision": decision, "reviewer_name": reviewer_name},
        ),
    }


def build_poc_milestones(candidate: dict[str, Any] | None) -> list[dict[str, Any]]:
    agent_name = (candidate or {}).get("candidate_agent_name") or "선정 Agent"
    process_name = (candidate or {}).get("process_name") or "선정 업무"
    risk_flags = (candidate or {}).get("risk_flags") or []
    needs_security_review = any(flag != "standard_review" for flag in risk_flags)

    milestones = [
        {
            "phase": "1. Scope Freeze",
            "period": "Week 1",
            "owner": "IT기획 + 현업 부서",
            "tasks": [
                f"{process_name}의 대상 사용자, 입력 문서, 기대 산출물 확정",
                "PoC 성공 기준과 제외 범위 확정",
                "RAG에 사용할 공식/내부 문서 목록 확정",
            ],
            "deliverable": "PoC 범위 정의서 및 데이터 접근 체크리스트",
        },
        {
            "phase": "2. Data & RAG Readiness",
            "period": "Week 2",
            "owner": "IT/데이터 담당자",
            "tasks": [
                "문서 수집·정제·chunking·embedding 재색인",
                "근거 label과 reference mapping 검증",
                "민감정보 포함 여부와 접근권한 점검",
            ],
            "deliverable": "RAG 인덱스 검증표 및 근거 품질 리포트",
        },
        {
            "phase": "3. Agent Prototype",
            "period": "Week 3-4",
            "owner": "AI/AX 개발 담당자",
            "tasks": [
                f"{agent_name} 질의응답/추천 흐름 구현",
                "Top candidate 업무 시나리오 5~10개 테스트",
                "근거 없는 답변 차단 및 citation validation 적용",
            ],
            "deliverable": "Agent prototype, 테스트 로그, 실패 케이스 목록",
        },
        {
            "phase": "4. User Review & Governance",
            "period": "Week 5",
            "owner": "현업 부서장 + 보안/거버넌스",
            "tasks": [
                "현업 사용자 리뷰와 Human Review 기록 수집",
                "오답·누락·권한 이슈 분류",
                "운영 전 통제 조건과 승인 절차 확정",
            ],
            "deliverable": "Human Review 결과표 및 Governance 체크리스트",
        },
        {
            "phase": "5. Go/No-Go Decision",
            "period": "Week 6",
            "owner": "AX 의사결정 협의체",
            "tasks": [
                "PoC KPI 달성 여부 평가",
                "ROI 추정치와 실제 테스트 절감 효과 비교",
                "확대 적용, 보완, 중단 중 후속 의사결정",
            ],
            "deliverable": "Go/No-Go 판단 보고서 및 후속 로드맵",
        },
    ]

    if needs_security_review:
        milestones[0]["tasks"].append("민감 키워드 탐지 업무로 분류하여 보안 담당자 사전 승인 확보")
        milestones[3]["tasks"].append("개인정보·기밀정보 처리 기준과 로그 보관 정책 검토")

    return milestones


def build_poc_kpis(candidate: dict[str, Any] | None) -> list[dict[str, Any]]:
    candidate = candidate or {}
    return [
        {
            "kpi": "근거 포함 응답률",
            "target": "90% 이상",
            "measurement": "Agent 응답 중 citation label을 포함한 응답 비율",
        },
        {
            "kpi": "업무 처리 시간 절감률",
            "target": f"{candidate.get('saving_rate', 50)}% 수준 검증",
            "measurement": "현행 처리 시간 대비 Agent 보조 처리 시간 비교",
        },
        {
            "kpi": "Human Review 승인율",
            "target": "80% 이상",
            "measurement": "현업/IT/보안 검토자가 승인한 응답 또는 추천 비율",
        },
        {
            "kpi": "근거 불일치율",
            "target": "5% 이하",
            "measurement": "citation과 실제 근거 내용이 불일치한 케이스 비율",
        },
        {
            "kpi": "보안 예외 발생 건수",
            "target": "0건",
            "measurement": "민감정보 노출, 권한 없는 문서 접근, 로그 누락 건수",
        },
    ]


def poc_delivery_planner_node(state: AXPlannerState) -> dict[str, Any]:
    node_name = "poc_delivery_planner"

    try:
        decision = state.get("human_review", {}).get("decision", "reject")

        ranking_items = state.get("priority_ranking", {}).get("items", [])
        recommended_items = [
            item for item in ranking_items if item.get("status") == "recommended"
        ]

        first_individual_poc = recommended_items[0] if recommended_items else None
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
                ],
                "exit_criteria": [
                    "KPI 목표 달성 여부 확인",
                    "보안/거버넌스 예외 없음 또는 보완계획 수립",
                    "현업 부서의 확대 적용/보류 의견 기록",
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
                    "milestone_count": len(result["poc_plan"]["milestones"]),
                },
            ),
        }

    except Exception as exc:
        return {
            "errors": append_error(state, node_name, exc),
            "audit_logs": append_audit(state, node_name, "failed"),
        }


def report_writer_node(state: AXPlannerState) -> dict[str, Any]:
    node_name = "report_writer"

    try:
        result = build_report_data(state)

        with SessionLocal() as db:
            save_analysis_result(
                db=db,
                project_id=int(state["project_id"]),
                node_name=node_name,
                result_json=result,
            )

        return {
            "report_data": result,
            "audit_logs": append_audit(
                state,
                node_name,
                "success",
                payload={
                    "section_count": len(result.get("sections", [])),
                    "reference_count": len(result.get("references", [])),
                    "evidence_count": len(state.get("evidence_items", [])),
                },
            ),
        }

    except Exception as exc:
        return {
            "errors": append_error(state, node_name, exc),
            "audit_logs": append_audit(state, node_name, "failed"),
        }


def docx_generator_node(state: AXPlannerState) -> dict[str, Any]:
    node_name = "docx_generator"

    try:
        from app.tools.docx_generator import generate_docx_report

        output_path = f"outputs/AX_Delivery_Planner_Report_{state['project_id']}.docx"

        generated_path = generate_docx_report(
            report_data=state.get("report_data", {}),
            output_path=output_path,
        )

        result = {
            "path": generated_path,
            "status": "created",
        }

        with SessionLocal() as db:
            save_analysis_result(
                db=db,
                project_id=int(state["project_id"]),
                node_name=node_name,
                result_json=result,
            )

        return {
            "report_docx_path": generated_path,
            "audit_logs": append_audit(
                state,
                node_name,
                "success",
                payload=result,
            ),
        }

    except Exception as exc:
        return {
            "errors": append_error(state, node_name, exc),
            "audit_logs": append_audit(state, node_name, "failed"),
        }
