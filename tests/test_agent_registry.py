from __future__ import annotations

import pytest

from app.agents.registry import AGENT_REGISTRY, get_agent_registry, get_agent_spec, get_tool_spec_for_node
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


def test_registry_contains_seven_expert_agents() -> None:
    registry = get_agent_registry()

    assert {agent["id"] for agent in registry} == EXPECTED_AGENT_IDS
    assert all("managed_nodes" in agent for agent in registry)
    assert all("capabilities" in agent for agent in registry)
    assert all("role_prompt" in agent for agent in registry)
    assert all("task_instructions" in agent for agent in registry)
    assert all("tool_specs" in agent for agent in registry)


def test_all_agent_specs_include_operational_prompt_fields() -> None:
    for agent in get_agent_registry():
        assert agent["role_prompt"]
        assert len(agent["role_prompt"]) >= 80
        assert agent["task_instructions"]
        assert agent["output_contract"]
        assert agent["quality_checks"]
        assert agent["handoff_notes"]
        assert agent["tool_specs"]


def test_agent_ids_are_unique() -> None:
    ids = [agent.id for agent in AGENT_REGISTRY]

    assert len(ids) == len(set(ids))


def test_tool_specs_cover_managed_nodes() -> None:
    for agent in get_agent_registry():
        tool_nodes = {
            node
            for tool_spec in agent.get("tool_specs", [])
            for node in tool_spec.get("nodes", [])
        }
        assert set(agent["managed_nodes"]).issubset(tool_nodes)


def test_process_diagnosis_agent_has_expert_prompt_and_capabilities() -> None:
    spec = get_agent_spec("process_diagnosis_agent")

    assert spec is not None
    assert spec["managed_nodes"] == ["process_analyzer", "data_readiness", "automation_feasibility"]
    assert "operations-analysis expert" in spec["role_prompt"]
    assert {capability["name"] for capability in spec["capabilities"]} == {
        "process_bottleneck_analysis",
        "data_readiness_scoring",
        "automation_feasibility_scoring",
    }
    assert get_tool_spec_for_node("process_diagnosis_agent", "data_readiness")["name"] == "data_readiness_scorer"


def test_evaluation_critic_agent_enforces_conservative_review_policy() -> None:
    spec = get_agent_spec("evaluation_critic_agent")

    assert spec is not None
    assert spec["human_review_required"] is True
    assert "independent quality gate" in spec["role_prompt"]
    assert "compliance_alignment_check" in spec["controls"]
    assert any("weak evidence" in check.lower() for check in spec["quality_checks"])


def test_evaluation_critic_agent_tool_permissions_use_expert_agent_id() -> None:
    assert_tools_allowed("evaluation_critic_agent", ["LLM critic", "quality gate", "llm_critic"])
    assert assert_tool_spec_allowed("evaluation_critic_agent", "llm_critic")["name"] == "llm_critic"

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
