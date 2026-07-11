# app/graph/nodes.py

"""AX 분석 workflow의 핵심 업무 node 구현.

프로젝트 데이터 로드, RAG 검색, 프로세스 분석, 데이터 준비도, 자동화 가능성, ROI,
risk, ranking, report data 생성 같은 주요 분석 node가 들어 있다.
"""

from __future__ import annotations

from typing import Any

from app.db.crud import (
    load_project_data,
    save_analysis_result,
    write_audit_log,
)
from app.db.database import SessionLocal
from app.graph.analysis_nodes import (
    automation_feasibility_node,
    data_readiness_node,
    priority_ranking_node,
    process_analyzer_node,
    risk_governance_node,
    roi_cost_node,
)
from app.graph.audit import append_audit, append_error
from app.graph.evidence_context import build_retrieval_state_payload
from app.graph.poc_node import poc_delivery_planner_node
from app.graph.review_node import human_review_node
from app.graph.state import AXPlannerState
from app.rag.retriever import retrieve_contexts_for_processes
from app.tools.report_data_builder import build_report_data


def load_project_data_node(state: AXPlannerState) -> dict[str, Any]:
    """project/company/process/document context를 DB에서 읽어 LangGraph state에 적재한다."""
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
    """업무별 RAG 검색을 실행하고 evidence_items와 used_sources를 state에 만든다."""
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

        retrieval_payload = build_retrieval_state_payload(
            contexts=contexts,
            documents=state.get("documents", []),
        )
        evidence_items = retrieval_payload["evidence_items"]
        used_sources = retrieval_payload["used_sources"]
        retrieval_query_plan = retrieval_payload["retrieval_query_plan"]

        return {
            "retrieved_contexts": contexts,
            **retrieval_payload,
            "audit_logs": append_audit(
                state,
                node_name=node_name,
                status="success",
                payload={
                    "context_groups": len(contexts),
                    "evidence_count": len(evidence_items),
                    "used_source_count": len(used_sources),
                    "query_strategy_count_per_process": {
                        process_id: len(plan or [])
                        for process_id, plan in retrieval_query_plan.items()
                    },
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


def report_writer_node(state: AXPlannerState) -> dict[str, Any]:
    """분석 state를 citation 포함 report_data로 변환한다."""
    node_name = "report_writer"

    try:
        result = build_report_data(state)
        model_selection = (result.get("generation") or {}).get("model_selection") or {}

        with SessionLocal() as db:
            save_analysis_result(
                db=db,
                project_id=int(state["project_id"]),
                node_name=node_name,
                result_json=result,
            )

        return {
            "report_data": result,
            "agent_model_decisions": [
                {
                    "agent_id": "delivery_orchestration_agent",
                    "stage_name": node_name,
                    "call_kind": "report_writer",
                    **model_selection,
                }
            ]
            if model_selection
            else [],
            "audit_logs": append_audit(
                state,
                node_name,
                "success",
                payload={
                    "section_count": len(result.get("sections", [])),
                    "reference_count": len(result.get("references", [])),
                    "evidence_count": len(state.get("evidence_items", [])),
                    "model_provider": model_selection.get("provider"),
                    "model": model_selection.get("model"),
                },
            ),
        }

    except Exception as exc:
        return {
            "errors": append_error(state, node_name, exc),
            "audit_logs": append_audit(state, node_name, "failed"),
        }


def docx_generator_node(state: AXPlannerState) -> dict[str, Any]:
    """report_data를 DOCX 파일로 렌더링하고 output path를 state에 저장한다."""
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
