from __future__ import annotations

from app.agents.runtime import (
    bind_agent_contract_to_result,
    build_agent_contract,
    get_agent_binding_for_node,
    get_agent_id_for_node,
    with_agent_contract,
)


def test_build_agent_contract_for_graph_node() -> None:
    contract = build_agent_contract("data_readiness")

    assert contract is not None
    assert contract["node_name"] == "data_readiness"
    assert contract["agent_id"] == "process_diagnosis_agent"
    assert contract["capability"] == "data_readiness_scoring"
    assert contract["node_role"] == "데이터 접근성, 문서 연결성, 접근권한 기반 readiness 분류"
    assert contract["implementation"] == "rule_plus_rag_deterministic_scoring"
    assert contract["contract_found"] is True
    assert "data_preparation_flag" in contract["controls"]


def test_node_to_expert_agent_mapping() -> None:
    assert get_agent_id_for_node("process_discovery_agent") == "company_onboarding_agent"
    assert get_agent_id_for_node("llm_critic") == "evaluation_critic_agent"
    assert get_agent_id_for_node("docx_generator") == "delivery_orchestration_agent"


def test_node_binding_includes_capability_and_role() -> None:
    binding = get_agent_binding_for_node("retrieve_context")

    assert binding == {
        "agent_id": "context_evidence_agent",
        "capability": "rag_evidence_retrieval",
        "node_role": "업무별 pgvector 검색, evidence item 생성, used_sources 구성",
    }


def test_bind_agent_contract_to_result_adds_contract_and_audit() -> None:
    result = bind_agent_contract_to_result(
        "roi_cost",
        {"roi_cost": {"summary": {"total_processes": 2}}, "audit_logs": []},
    )

    assert result["agent_contracts"][0]["agent_id"] == "business_case_agent"
    assert result["agent_contracts"][0]["capability"] == "roi_cost_calculation"
    assert result["agent_contracts"][0]["implementation"] == "deterministic_calculation_and_weighted_ranking"
    assert result["audit_logs"][0]["status"] == "agent_contract_bound"
    assert result["audit_logs"][0]["payload"]["agent_id"] == "business_case_agent"
    assert result["audit_logs"][0]["payload"]["capability"] == "roi_cost_calculation"


def test_with_agent_contract_wraps_node_result() -> None:
    def sample_node(state: dict) -> dict:
        return {"data_readiness": {"summary": {"total_processes": 1}}, "audit_logs": []}

    wrapped = with_agent_contract("data_readiness", sample_node)
    result = wrapped({})

    assert result["agent_contracts"][0]["agent_id"] == "process_diagnosis_agent"
    assert result["agent_contracts"][0]["capability"] == "data_readiness_scoring"
    assert result["audit_logs"][0]["status"] == "agent_contract_bound"
