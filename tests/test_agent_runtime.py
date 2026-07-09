from __future__ import annotations

import pytest

from app.agents.expert_executor import expert_executed_node
from app.agents.registry import AGENT_REGISTRY, get_agent_registry, get_agent_spec, get_tool_spec_for_node
from app.agents.runtime import build_agent_contract, get_agent_binding_for_node, get_agent_id_for_node
from app.agents.tool_guard import AgentToolPermissionError, assert_tools_allowed, assert_tool_spec_allowed


EXPECTED_AGENT_IDS = {
    "company_onboarding_agent",
    "context_evidence_agent",
    "process_diagnosis_agent",
    "business_case_agent",
    "governance_compliance_agent",
    "evaluation_critic_agent",
    "delivery_orchestration_agent",
}


def test_registry_contains_only_expert_agents() -> None:
    registry = get_agent_registry()

    assert {agent["id"] for agent in registry} == EXPECTED_AGENT_IDS
    assert len(AGENT_REGISTRY) == len(EXPECTED_AGENT_IDS)
    assert len({agent.id for agent in AGENT_REGISTRY}) == len(EXPECTED_AGENT_IDS)


@pytest.mark.parametrize("agent", get_agent_registry())
def test_agent_specs_include_prompt_contract_and_tool_specs(agent: dict) -> None:
    assert agent["role_prompt"]
    assert len(agent["role_prompt"]) >= 80
    assert agent["task_instructions"]
    assert agent["output_contract"]
    assert agent["quality_checks"]
    assert agent["handoff_notes"]
    assert agent["tool_specs"]

    tool_nodes = {
        node
        for tool_spec in agent.get("tool_specs", [])
        for node in tool_spec.get("nodes", [])
    }
    assert set(agent["managed_nodes"]).issubset(tool_nodes)


def test_process_diagnosis_contract_and_tool_mapping() -> None:
    spec = get_agent_spec("process_diagnosis_agent")
    contract = build_agent_contract("data_readiness")

    assert spec is not None
    assert spec["managed_nodes"] == ["process_analyzer", "data_readiness", "automation_feasibility"]
    assert "operations-analysis expert" in spec["role_prompt"]
    assert {capability["name"] for capability in spec["capabilities"]} == {
        "process_bottleneck_analysis",
        "data_readiness_scoring",
        "automation_feasibility_scoring",
    }
    assert get_tool_spec_for_node("process_diagnosis_agent", "data_readiness")["name"] == "data_readiness_scorer"
    assert contract is not None
    assert contract["agent_id"] == "process_diagnosis_agent"
    assert contract["capability"] == "data_readiness_scoring"
    assert contract["selected_tool_spec"]["name"] == "data_readiness_scorer"


def test_node_to_expert_agent_mapping() -> None:
    assert get_agent_id_for_node("process_discovery_agent") == "company_onboarding_agent"
    assert get_agent_id_for_node("llm_critic") == "evaluation_critic_agent"
    assert get_agent_id_for_node("agent_replan") == "evaluation_critic_agent"
    assert get_agent_id_for_node("docx_generator") == "delivery_orchestration_agent"


def test_node_binding_includes_capability_and_role() -> None:
    binding = get_agent_binding_for_node("retrieve_context")

    assert binding == {
        "agent_id": "context_evidence_agent",
        "capability": "rag_evidence_retrieval",
        "node_role": "업무별 pgvector 검색, evidence item 생성, used_sources 구성",
    }


def test_evaluation_critic_permissions_use_expert_agent_id() -> None:
    spec = get_agent_spec("evaluation_critic_agent")

    assert spec is not None
    assert spec["human_review_required"] is True
    assert "independent quality gate" in spec["role_prompt"]
    assert "compliance_alignment_check" in spec["controls"]
    assert_tools_allowed("evaluation_critic_agent", ["LLM critic", "quality gate", "llm_critic", "replan_router"])
    assert assert_tool_spec_allowed("evaluation_critic_agent", "llm_critic")["name"] == "llm_critic"
    assert assert_tool_spec_allowed("evaluation_critic_agent", "replan_router")["name"] == "replan_router"

    with pytest.raises(AgentToolPermissionError):
        assert_tools_allowed("agent_evaluator_agent", ["LLM critic"])


def test_delivery_orchestration_agent_uses_human_review_gate() -> None:
    spec = get_agent_spec("delivery_orchestration_agent")

    assert spec is not None
    assert spec["human_review_required"] is True
    assert "human_review_gate" in spec["controls"]
    assert "final AX delivery planning supervisor" in spec["role_prompt"]
    assert any("Do not select excluded" in check for check in spec["quality_checks"])
    assert get_tool_spec_for_node("delivery_orchestration_agent", "docx_generator")["name"] == "docx_exporter"


def test_expert_executor_runs_node_through_tool_call() -> None:
    def sample_node(state: dict) -> dict:
        return {"data_readiness": {"summary": {"total_processes": 1}}, "audit_logs": []}

    wrapped = expert_executed_node("data_readiness", sample_node)
    result = wrapped({"project_id": 1, "company_id": 1, "business_processes": [{"id": 1}]})

    assert result["data_readiness"]["summary"]["total_processes"] == 1
    assert result["agent_contracts"][0]["agent_id"] == "process_diagnosis_agent"
    assert result["agent_contracts"][0]["selected_tool"] == "data_readiness_scorer"
    assert result["agent_tool_calls"][0]["tool_name"] == "data_readiness_scorer"
    assert [log["status"] for log in result["audit_logs"]][:2] == [
        "agent_tool_call_started",
        "agent_tool_call_succeeded",
    ]
