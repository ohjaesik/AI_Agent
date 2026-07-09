from __future__ import annotations

from app.agents.expert_registry import get_expert_agent_registry, get_expert_agent_spec
from app.agents.registry import get_agent_registry, get_agent_spec


EXPECTED_EXPERT_AGENT_IDS = {
    "company_onboarding_agent",
    "context_evidence_agent",
    "process_diagnosis_agent",
    "business_case_agent",
    "governance_compliance_agent",
    "evaluation_critic_agent",
    "delivery_orchestration_agent",
}


def test_expert_registry_contains_seven_expert_agents() -> None:
    registry = get_expert_agent_registry()

    assert {agent["id"] for agent in registry} == EXPECTED_EXPERT_AGENT_IDS
    assert all("managed_nodes" in agent for agent in registry)
    assert all("capabilities" in agent for agent in registry)


def test_backward_compatible_registry_returns_expert_agents() -> None:
    registry = get_agent_registry()

    assert {agent["id"] for agent in registry} == EXPECTED_EXPERT_AGENT_IDS
    assert all("managed_nodes" in agent for agent in registry)
    assert all("capabilities" in agent for agent in registry)


def test_get_agent_spec_is_expert_spec() -> None:
    spec = get_agent_spec("process_diagnosis_agent")

    assert spec is not None
    assert spec["id"] == "process_diagnosis_agent"
    assert spec["managed_nodes"] == ["process_analyzer", "data_readiness", "automation_feasibility"]
    assert [capability["name"] for capability in spec["capabilities"]] == [
        "process_bottleneck_analysis",
        "data_readiness_scoring",
        "automation_feasibility_scoring",
    ]


def test_expert_agent_spec_lookup() -> None:
    spec = get_expert_agent_spec("delivery_orchestration_agent")

    assert spec is not None
    assert spec["managed_nodes"] == ["human_review", "poc_delivery_planner", "report_writer", "docx_generator"]
    assert {capability["name"] for capability in spec["capabilities"]} == {
        "human_review_gate",
        "poc_delivery_planning",
        "report_generation",
        "docx_export",
    }
