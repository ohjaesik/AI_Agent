# app/agents/supervisor_flow.py

from __future__ import annotations

from typing import Any

SUPERVISOR_AGENT_ID = "ax_delivery_supervisor_agent"
SUPERVISOR_AGENT_NAME = "AX Delivery Supervisor Agent"

AGENT_TASKS: dict[str, str] = {
    "company_onboarding_agent": "기업 식별, 공식자료 수집, 초기 업무 후보 생성을 위임한다.",
    "context_evidence_agent": "프로젝트 context와 RAG 근거 패키지 생성을 위임한다.",
    "process_diagnosis_agent": "업무 병목, 데이터 준비도, 자동화 가능성 진단을 위임한다.",
    "governance_compliance_agent": "보안·개인정보·고영향·규제 리스크 검토를 위임한다.",
    "business_case_agent": "ROI와 PoC 우선순위 산정을 위임한다.",
    "evaluation_critic_agent": "근거 충분성, confidence, replan 필요성 검증을 위임한다.",
    "delivery_orchestration_agent": "Human Review, PoC 계획, 보고서, DOCX 산출을 위임한다.",
}

ARTIFACT_KEYS_BY_AGENT: dict[str, list[str]] = {
    "company_onboarding_agent": ["company_profile", "official_sources", "document_ids", "process_specs", "process_ids", "project_id"],
    "context_evidence_agent": ["project", "company_profile", "business_processes", "documents", "retrieved_contexts", "evidence_items", "used_sources"],
    "process_diagnosis_agent": ["process_analysis", "data_readiness", "automation_feasibility"],
    "governance_compliance_agent": ["risk_governance", "compliance_assessment"],
    "business_case_agent": ["roi_cost", "priority_ranking"],
    "evaluation_critic_agent": ["agent_evaluation", "priority_ranking", "replan_request"],
    "delivery_orchestration_agent": ["human_review", "poc_plan", "report_data", "report_docx_path"],
}

HANDOFFS_BY_NODE: dict[str, list[dict[str, Any]]] = {
    "company_profile_agent": [
        {
            "to_agent": "company_onboarding_agent",
            "target_nodes": ["source_ingestion_agent", "process_discovery_agent"],
            "payload_keys": ["company_profile", "company_id", "resolved_company_name", "dart_company"],
            "reason": "기업 식별 결과를 공식자료 수집과 업무 후보 생성 단계에 전달한다.",
        }
    ],
    "source_ingestion_agent": [
        {
            "to_agent": "company_onboarding_agent",
            "target_nodes": ["process_discovery_agent"],
            "payload_keys": ["official_docs", "official_sources", "combined_text", "document_ids"],
            "reason": "공식자료 수집 결과를 업무 후보 생성 Agent task에 전달한다.",
        }
    ],
    "process_discovery_agent": [
        {
            "to_agent": "context_evidence_agent",
            "target_nodes": ["load_project_data", "retrieve_context"],
            "payload_keys": ["project_id", "company_id", "process_ids", "document_ids"],
            "reason": "생성된 업무 후보와 문서 ID를 본 분석 그래프의 근거 검색 Agent에게 넘긴다.",
        }
    ],
    "load_project_data": [
        {
            "to_agent": "context_evidence_agent",
            "target_nodes": ["retrieve_context"],
            "payload_keys": ["project", "company_profile", "business_processes", "documents", "systems"],
            "reason": "DB context를 RAG 근거 검색 단계에 전달한다.",
        }
    ],
    "retrieve_context": [
        {
            "to_agent": "process_diagnosis_agent",
            "target_nodes": ["process_analyzer", "data_readiness", "automation_feasibility"],
            "payload_keys": ["business_processes", "retrieved_contexts", "evidence_items", "used_sources"],
            "reason": "업무 진단 Agent가 분석할 근거 패키지를 전달한다.",
        },
        {
            "to_agent": "governance_compliance_agent",
            "target_nodes": ["risk_governance", "compliance_assessment"],
            "payload_keys": ["business_processes", "retrieved_contexts", "evidence_items", "used_sources"],
            "reason": "거버넌스 Agent가 리스크를 판단할 근거 패키지를 전달한다.",
        },
    ],
    "process_analyzer": [
        {
            "to_agent": "business_case_agent",
            "target_nodes": ["priority_ranking"],
            "payload_keys": ["process_analysis"],
            "reason": "업무 병목 분석 결과를 우선순위 산정 Agent에게 전달한다.",
        }
    ],
    "data_readiness": [
        {
            "to_agent": "business_case_agent",
            "target_nodes": ["priority_ranking"],
            "payload_keys": ["data_readiness"],
            "reason": "데이터 준비도 결과를 우선순위 산정 Agent에게 전달한다.",
        }
    ],
    "automation_feasibility": [
        {
            "to_agent": "business_case_agent",
            "target_nodes": ["roi_cost", "priority_ranking"],
            "payload_keys": ["automation_feasibility"],
            "reason": "자동화 가능성 결과를 ROI와 우선순위 산정 Agent에게 전달한다.",
        }
    ],
    "risk_governance": [
        {
            "to_agent": "governance_compliance_agent",
            "target_nodes": ["compliance_assessment"],
            "payload_keys": ["risk_governance"],
            "reason": "리스크 flag를 규제 mapping 단계에 전달한다.",
        }
    ],
    "compliance_assessment": [
        {
            "to_agent": "business_case_agent",
            "target_nodes": ["priority_ranking"],
            "payload_keys": ["compliance_assessment"],
            "reason": "규제·검토 필요 조건을 우선순위 산정 Agent에게 전달한다.",
        }
    ],
    "roi_cost": [
        {
            "to_agent": "business_case_agent",
            "target_nodes": ["priority_ranking"],
            "payload_keys": ["roi_cost"],
            "reason": "ROI 산정 결과를 후보 ranking 단계에 전달한다.",
        }
    ],
    "priority_ranking": [
        {
            "to_agent": "evaluation_critic_agent",
            "target_nodes": ["agent_evaluator", "llm_critic"],
            "payload_keys": ["priority_ranking", "roi_cost", "compliance_assessment"],
            "reason": "Business Case Agent의 추천 결과를 Evaluation & Critic Agent에게 검증 요청한다.",
        }
    ],
    "agent_evaluator": [
        {
            "to_agent": "evaluation_critic_agent",
            "target_nodes": ["llm_critic", "agent_replan"],
            "payload_keys": ["agent_evaluation", "priority_ranking", "replan_request"],
            "reason": "정량 검증 결과를 critic/replan 판단 단계에 전달한다.",
        }
    ],
    "llm_critic": [
        {
            "to_agent": "delivery_orchestration_agent",
            "target_nodes": ["human_review"],
            "payload_keys": ["agent_evaluation", "priority_ranking", "replan_request"],
            "reason": "검증된 후보 패키지를 Human Review Agent에게 전달한다.",
        }
    ],
    "agent_replan": [
        {
            "to_agent": "context_evidence_agent",
            "target_nodes": ["retrieve_context"],
            "payload_keys": ["replan_request", "retrieved_contexts", "evidence_items", "used_sources"],
            "reason": "추가 근거 수집 결과를 Context & Evidence Agent에게 다시 넘겨 재검색한다.",
        }
    ],
    "human_review": [
        {
            "to_agent": "delivery_orchestration_agent",
            "target_nodes": ["poc_delivery_planner"],
            "payload_keys": ["human_review", "priority_ranking", "agent_evaluation"],
            "reason": "승인/수정/거절 기록을 PoC 계획 Agent task에 전달한다.",
        }
    ],
    "poc_delivery_planner": [
        {
            "to_agent": "delivery_orchestration_agent",
            "target_nodes": ["report_writer"],
            "payload_keys": ["poc_plan", "human_review", "priority_ranking"],
            "reason": "PoC 계획 결과를 보고서 작성 Agent task에 전달한다.",
        }
    ],
    "report_writer": [
        {
            "to_agent": "delivery_orchestration_agent",
            "target_nodes": ["docx_generator"],
            "payload_keys": ["report_data"],
            "reason": "보고서 데이터를 DOCX export Agent task에 전달한다.",
        }
    ],
    "docx_generator": [
        {
            "to_agent": SUPERVISOR_AGENT_ID,
            "target_nodes": ["final"],
            "payload_keys": ["report_docx_path", "report_data", "audit_logs"],
            "reason": "최종 산출물을 상위 Supervisor Agent에게 반환한다.",
        }
    ],
}


def present_payload_keys(result: dict[str, Any], keys: list[str]) -> list[str]:
    return [key for key in keys if key in result and result.get(key) not in (None, [], {}, "")]


def build_supervisor_step(
    *,
    node_name: str,
    agent_id: str,
    contract: dict[str, Any],
    assigned_tools: list[dict[str, Any]],
    loop_limit: int,
) -> dict[str, Any]:
    return {
        "supervisor_agent_id": SUPERVISOR_AGENT_ID,
        "supervisor_agent_name": SUPERVISOR_AGENT_NAME,
        "delegated_to": agent_id,
        "delegated_agent_name": contract.get("agent_name") or agent_id,
        "node_name": node_name,
        "capability": contract.get("capability"),
        "task": AGENT_TASKS.get(agent_id, contract.get("node_role") or "Agent task"),
        "assigned_tools": [tool.get("name") for tool in assigned_tools],
        "loop_limit": loop_limit,
        "handoff_policy": "result_artifact_to_next_agent",
    }


def build_agent_artifact(
    *,
    node_name: str,
    agent_id: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    expected_keys = ARTIFACT_KEYS_BY_AGENT.get(agent_id, [])
    output_keys = present_payload_keys(result, expected_keys)
    return {
        "agent_id": agent_id,
        "node_name": node_name,
        "artifact_name": f"{agent_id}:{node_name}:result_package",
        "output_keys": output_keys,
        "has_output": bool(output_keys),
    }


def build_agent_handoffs(
    *,
    node_name: str,
    from_agent: str,
    result: dict[str, Any],
    loop_index: int | None = None,
) -> list[dict[str, Any]]:
    handoffs: list[dict[str, Any]] = []
    for spec in HANDOFFS_BY_NODE.get(node_name, []):
        payload_keys = list(spec.get("payload_keys", []))
        available_keys = present_payload_keys(result, payload_keys)
        handoffs.append(
            {
                "supervisor_agent_id": SUPERVISOR_AGENT_ID,
                "from_agent": from_agent,
                "to_agent": spec.get("to_agent"),
                "source_node": node_name,
                "target_nodes": list(spec.get("target_nodes", [])),
                "payload_keys": payload_keys,
                "available_payload_keys": available_keys,
                "handoff_ready": bool(available_keys) or spec.get("to_agent") == SUPERVISOR_AGENT_ID,
                "handoff_reason": spec.get("reason"),
                "loop_index": loop_index,
            }
        )
    return handoffs
