# app/agents/runtime.py

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, TypeVar

from app.agents.registry import get_capability_for_node, get_agent_spec, get_tool_spec_for_node

StateT = TypeVar("StateT", bound=dict[str, Any])

NODE_AGENT_BINDINGS: dict[str, dict[str, str]] = {
    "company_profile_agent": {"agent_id": "company_onboarding_agent", "capability": "company_profile_resolution", "node_role": "회사 식별, OpenDART 조회, company profile 생성/갱신"},
    "source_ingestion_agent": {"agent_id": "company_onboarding_agent", "capability": "official_source_ingestion", "node_role": "공식 URL과 공시 자료 수집, 문서 저장, RAG 색인 준비"},
    "process_discovery_agent": {"agent_id": "company_onboarding_agent", "capability": "process_candidate_discovery", "node_role": "공식자료 기반 AX 후보 업무 생성과 evidence label 연결"},
    "load_project_data": {"agent_id": "context_evidence_agent", "capability": "project_context_loading", "node_role": "project, company, process, document, system 정보를 DB에서 로드"},
    "retrieve_context": {"agent_id": "context_evidence_agent", "capability": "rag_evidence_retrieval", "node_role": "업무별 pgvector 검색, evidence item 생성, used_sources 구성"},
    "process_analyzer": {"agent_id": "process_diagnosis_agent", "capability": "process_bottleneck_analysis", "node_role": "업무 문제, 대상 사용자, 현재 흐름, 문서 의존성, 근거 요약"},
    "data_readiness": {"agent_id": "process_diagnosis_agent", "capability": "data_readiness_scoring", "node_role": "데이터 접근성, 문서 연결성, 접근권한 기반 readiness 분류"},
    "automation_feasibility": {"agent_id": "process_diagnosis_agent", "capability": "automation_feasibility_scoring", "node_role": "반복성, 기대효과, 구현 가능성, 위험도 기반 assistive automation 가능성 계산"},
    "roi_cost": {"agent_id": "business_case_agent", "capability": "roi_cost_calculation", "node_role": "현재 비용, 예상 비용, 절감률, PoC 비용 계산"},
    "priority_ranking": {"agent_id": "business_case_agent", "capability": "candidate_priority_ranking", "node_role": "효과, 반복성, readiness, ROI, risk 기반 우선순위 산정"},
    "risk_governance": {"agent_id": "governance_compliance_agent", "capability": "risk_signal_screening", "node_role": "업무명, 문제, workflow, 문서, RAG context에서 risk flag 탐지"},
    "compliance_assessment": {"agent_id": "governance_compliance_agent", "capability": "regulatory_mapping", "node_role": "EU AI Act, Korea AI Basic Act proxy, privacy/security mapping 생성"},
    "agent_evaluator": {"agent_id": "evaluation_critic_agent", "capability": "deterministic_agent_evaluation", "node_role": "evidence coverage, data confidence, rationale coverage, compliance alignment 계산"},
    "llm_critic": {"agent_id": "evaluation_critic_agent", "capability": "llm_second_opinion", "node_role": "LLM 기반 보조 검토와 confidence calibration"},
    "agent_replan": {"agent_id": "evaluation_critic_agent", "capability": "bounded_replan", "node_role": "추가 근거가 유효할 때 제한된 replan loop 수행"},
    "human_review": {"agent_id": "delivery_orchestration_agent", "capability": "human_review_gate", "node_role": "approve/edit/reject 검토 기록 수집과 graph resume"},
    "poc_delivery_planner": {"agent_id": "delivery_orchestration_agent", "capability": "poc_delivery_planning", "node_role": "승인 후보 기반 6주 PoC 계획, milestone, KPI 생성"},
    "report_writer": {"agent_id": "delivery_orchestration_agent", "capability": "report_generation", "node_role": "근거 기반 report_data 생성, LLM 문장화, citation validation"},
    "docx_generator": {"agent_id": "delivery_orchestration_agent", "capability": "docx_export", "node_role": "report_data를 DOCX 파일로 내보내기"},
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_agent_id_for_node(node_name: str) -> str | None:
    binding = NODE_AGENT_BINDINGS.get(node_name)
    return binding.get("agent_id") if binding else None


def get_agent_binding_for_node(node_name: str) -> dict[str, str] | None:
    binding = NODE_AGENT_BINDINGS.get(node_name)
    return dict(binding) if binding else None


def build_agent_contract(node_name: str) -> dict[str, Any] | None:
    binding = get_agent_binding_for_node(node_name)
    if not binding:
        return None

    agent_id = binding["agent_id"]
    spec = get_agent_spec(agent_id)
    if not spec:
        return {
            "node_name": node_name,
            "agent_id": agent_id,
            "agent_name": agent_id,
            "capability": binding.get("capability"),
            "node_role": binding.get("node_role"),
            "contract_found": False,
        }

    capability = get_capability_for_node(spec, node_name) or {
        "name": binding.get("capability"),
        "node_role": binding.get("node_role"),
        "nodes": [node_name],
    }
    selected_tool_spec = get_tool_spec_for_node(agent_id, node_name)

    return {
        "node_name": node_name,
        "agent_id": spec["id"],
        "agent_name": spec["name"],
        "category": spec["category"],
        "implementation": spec["implementation"],
        "capability": capability.get("name") or binding.get("capability"),
        "node_role": capability.get("node_role") or binding.get("node_role"),
        "managed_nodes": list(spec.get("managed_nodes", [])),
        "capability_nodes": list(capability.get("nodes", [node_name])),
        "tools": list(spec.get("tools", [])),
        "tool_specs": list(spec.get("tool_specs", [])),
        "selected_tool_spec": selected_tool_spec,
        "controls": list(spec.get("controls", [])),
        "human_review_required": bool(spec.get("human_review_required", False)),
        "role_prompt": spec.get("role_prompt", ""),
        "task_instructions": list(spec.get("task_instructions", [])),
        "quality_checks": list(spec.get("quality_checks", [])),
        "output_contract": list(spec.get("output_contract", [])),
        "contract_found": True,
    }


def build_contract_audit_log(node_name: str, contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "node": node_name,
        "status": "agent_contract_bound",
        "timestamp": utc_now(),
        "payload": {
            "agent_id": contract.get("agent_id"),
            "agent_name": contract.get("agent_name"),
            "capability": contract.get("capability"),
            "node_role": contract.get("node_role"),
            "selected_tool": (contract.get("selected_tool_spec") or {}).get("name"),
            "implementation": contract.get("implementation"),
            "category": contract.get("category"),
            "tools": contract.get("tools", []),
            "controls": contract.get("controls", []),
            "human_review_required": contract.get("human_review_required", False),
            "contract_found": contract.get("contract_found", False),
        },
    }


def bind_agent_contract_to_result(node_name: str, result: dict[str, Any]) -> dict[str, Any]:
    contract = build_agent_contract(node_name)
    if contract is None:
        return result

    bound = dict(result)
    bound["agent_contracts"] = list(bound.get("agent_contracts", [])) + [contract]
    bound["audit_logs"] = list(bound.get("audit_logs", [])) + [build_contract_audit_log(node_name, contract)]
    return bound


def with_agent_contract(node_name: str, node_fn: Callable[[StateT], dict[str, Any]]) -> Callable[[StateT], dict[str, Any]]:
    def _node(state: StateT) -> dict[str, Any]:
        result = node_fn(state)
        return bind_agent_contract_to_result(node_name, result)

    _node.__name__ = f"contract_bound_{node_name}"
    return _node
