"""Agent registry, tool permission, handoff trace, runtime loop 구조를 검증한다.
"""

from __future__ import annotations

import pytest

from app.agents.expert_executor import expert_executed_node
from app.agents.handoff import AGENT_TO_PACKAGE, HANDOFF_RULES, attach_agent_stage_outputs
from app.agents.registry import (
    AGENT_REGISTRY,
    MAX_TOOL_CANDIDATES_PER_NODE,
    get_agent_registry,
    get_agent_spec,
    get_tool_spec_for_node,
    get_tool_specs_for_node,
)
from app.agents.runtime import build_agent_contract, get_agent_binding_for_node, get_agent_id_for_node
from app.agents.tool_guard import AgentToolPermissionError, assert_tools_allowed, assert_tool_spec_allowed
from app.graph.workflow import AGENT_STAGE_NODES, AGENT_STAGE_TO_AGENT_ID
from app.rag.retriever import build_process_retrieval_queries


EXPECTED_AGENT_IDS = {
    "company_onboarding_agent",
    "context_evidence_agent",
    "process_diagnosis_agent",
    "business_case_agent",
    "governance_compliance_agent",
    "evaluation_critic_agent",
    "delivery_orchestration_agent",
}

ALL_BOUND_NODES = [
    "company_profile_agent",
    "source_ingestion_agent",
    "process_discovery_agent",
    "load_project_data",
    "retrieve_context",
    "process_analyzer",
    "data_readiness",
    "automation_feasibility",
    "roi_cost",
    "priority_ranking",
    "risk_governance",
    "compliance_assessment",
    "agent_evaluator",
    "llm_critic",
    "agent_replan",
    "human_review",
    "poc_delivery_planner",
    "report_writer",
    "docx_generator",
]


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


@pytest.mark.parametrize("node_name", ALL_BOUND_NODES)
def test_each_node_has_bounded_candidate_tools(node_name: str) -> None:
    agent_id = get_agent_id_for_node(node_name)

    assert agent_id is not None
    specs = get_tool_specs_for_node(agent_id, node_name)
    assert 1 <= len(specs) <= MAX_TOOL_CANDIDATES_PER_NODE


def test_ax_workflow_is_grouped_by_expert_agent_stages() -> None:
    assert AGENT_STAGE_NODES == {
        "context_evidence_agent": ["load_project_data", "retrieve_context"],
        "process_diagnosis_agent": ["process_analyzer", "data_readiness", "automation_feasibility"],
        "governance_compliance_agent": ["risk_governance", "compliance_assessment"],
        "business_case_agent": ["roi_cost", "priority_ranking"],
        "evaluation_critic_agent": ["agent_evaluator", "llm_critic"],
        "agent_replan": ["agent_replan"],
        "delivery_orchestration_agent": ["human_review", "poc_delivery_planner", "report_writer", "docx_generator"],
    }
    assert AGENT_STAGE_TO_AGENT_ID["agent_replan"] == "evaluation_critic_agent"
    assert AGENT_TO_PACKAGE["business_case_agent"] == "business_case_package"
    assert HANDOFF_RULES["business_case_agent"][0]["to_agent"] == "evaluation_critic_agent"
    assert HANDOFF_RULES["evaluation_critic_agent"][0]["to_agent"] == "context_evidence_agent"


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
    assert [item["name"] for item in get_tool_specs_for_node("process_diagnosis_agent", "data_readiness")] == [
        "data_readiness_scorer",
        "data_gap_detector",
    ]
    assert contract is not None
    assert contract["agent_id"] == "process_diagnosis_agent"
    assert contract["capability"] == "data_readiness_scoring"
    assert contract["selected_tool_spec"]["name"] == "data_readiness_scorer"
    assert [item["name"] for item in contract["candidate_tool_specs"]] == ["data_readiness_scorer", "data_gap_detector"]


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
    assert_tools_allowed("evaluation_critic_agent", ["LLM critic", "quality gate", "llm_critic", "replan_router", "critic_replan_decider"])
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


def test_expert_executor_runs_assigned_tool_loop() -> None:
    def sample_node(state: dict) -> dict:
        return {"data_readiness": {"summary": {"total_processes": 1}}, "audit_logs": []}

    wrapped = expert_executed_node("data_readiness", sample_node)
    result = wrapped({"project_id": 1, "company_id": 1, "business_processes": [{"id": 1}]})

    assert result["data_readiness"]["summary"]["total_processes"] == 1
    assert result["agent_contracts"][0]["agent_id"] == "process_diagnosis_agent"
    assert result["agent_contracts"][0]["selected_tool"] == "data_readiness_scorer"
    assert result["agent_contracts"][0]["candidate_tools"] == ["data_readiness_scorer", "data_gap_detector"]
    assert result["agent_contracts"][0]["agent_loop_mode"] == "expert_agent_supervisor_loop"
    assert result["agent_tool_calls"][0]["tool_name"] == "data_readiness_scorer"
    assert result["agent_tool_calls"][1]["tool_name"] == "data_gap_detector"
    assert result["agent_tool_calls"][0]["executes_node"] is True
    assert result["agent_tool_calls"][1]["executes_node"] is False
    assert result["agent_tool_calls"][0]["planner_used_llm"] is False
    assert result["agent_loop_iterations"][0]["assigned_tools_executed"] == ["data_readiness_scorer", "data_gap_detector"]
    assert [log["status"] for log in result["audit_logs"]][:2] == [
        "agent_tool_call_started",
        "agent_tool_call_succeeded",
    ]
    assert result["agent_decisions"][0]["phase"] == "agent_tool_loop"
    assert result["agent_decisions"][-1]["phase"] == "post_tool_observation"


def test_retrieval_query_builder_creates_three_search_strategies() -> None:
    queries = build_process_retrieval_queries(
        {
            "id": 1,
            "name": "계약 검토",
            "problem": "반복 검토와 누락 확인이 오래 걸림",
            "current_workflow": "담당자가 계약서와 내부 규정을 대조한다.",
            "candidate_agent_name": "Contract Review Agent",
            "target_user": "법무팀",
        }
    )

    assert [item["strategy"] for item in queries] == [
        "workflow_full_context",
        "problem_and_user_intent",
        "automation_evidence_keywords",
    ]
    assert all(item["query"] for item in queries)


def test_handoff_records_selected_tools_from_stage_result() -> None:
    result = attach_agent_stage_outputs(
        state={
            "business_processes": [{"id": 1}],
            "retrieved_contexts": {"1": [{"chunk_id": 10}]},
            "evidence_items": [{"evidence_id": "rag-10"}],
            "current_supervisor_delegation": {
                "stage_name": "context_evidence_agent",
                "tool_policy": [
                    {
                        "node_name": "retrieve_context",
                        "tool_priorities": ["rag_retriever", "evidence_gap_detector"],
                        "autonomy": "auto_execute",
                    }
                ],
            },
        },
        result={
            "agent_tool_calls": [
                {
                    "node_name": "retrieve_context",
                    "agent_id": "context_evidence_agent",
                    "tool_name": "rag_retriever",
                    "tool_purpose": "execute",
                    "tool_uses_llm": False,
                    "executes_node": True,
                    "selection_reason": "primary evidence retrieval",
                }
            ]
        },
        agent_id="context_evidence_agent",
        stage_name="context_evidence_agent",
        executed_nodes=["retrieve_context"],
        loop_index=1,
    )

    assert result["agent_handoffs"][0]["selected_tools"] == ["rag_retriever"]
    assert result["agent_handoffs"][0]["supervisor_tool_policy"][0]["tool_priorities"] == [
        "rag_retriever",
        "evidence_gap_detector",
    ]


def test_evaluation_critic_distinguishes_insufficient_review_and_recommended() -> None:
    def sample_node(state: dict) -> dict:
        return {
            "priority_ranking": {
                "items": [
                    {"process_id": 1, "status": "recommended", "candidate_agent_name": "Severe Gap Agent"},
                    {"process_id": 2, "status": "recommended", "candidate_agent_name": "Weak Evidence Agent"},
                    {"process_id": 3, "status": "recommended", "candidate_agent_name": "Clean Agent"},
                ],
                "summary": {"recommended_count": 3},
            },
            "agent_evaluation": {
                "items": [
                    {
                        "process_id": 1,
                        "candidate_agent_name": "Severe Gap Agent",
                        "requires_additional_evidence": True,
                        "predicted_status": "evidence_insufficient",
                        "evidence_coverage": 0.0,
                        "confidence_score": 0.30,
                    },
                    {
                        "process_id": 2,
                        "candidate_agent_name": "Weak Evidence Agent",
                        "requires_additional_evidence": True,
                        "predicted_status": "human_review_required",
                        "evidence_coverage": 0.35,
                        "confidence_score": 0.72,
                    },
                ],
                "summary": {"additional_evidence_required_count": 2},
            },
            "audit_logs": [],
        }

    wrapped = expert_executed_node("agent_evaluator", sample_node)
    result = wrapped({"project_id": 1, "company_id": 1, "priority_ranking": {"items": [{"process_id": 1}]}})

    called_tools = [item["tool_name"] for item in result["agent_tool_calls"]]
    assert called_tools[:3] == ["evidence_quality_gate", "review_status_calibrator", "evidence_replan_decider"]
    assert result["agent_contracts"][0]["selected_tool"] == "evidence_replan_decider"
    assert result["priority_ranking"]["items"][0]["status"] == "evidence_insufficient"
    assert result["priority_ranking"]["items"][1]["status"] == "human_review_required"
    assert result["priority_ranking"]["items"][2]["status"] == "recommended"
    assert result["priority_ranking"]["summary"]["evidence_insufficient_count"] == 1
    assert result["priority_ranking"]["summary"]["human_review_required_count"] == 1
    assert result["priority_ranking"]["summary"]["recommended_count"] == 1
    assert result["agent_evaluation"]["agent_decision"]["insufficient_process_ids"] == [1]
    assert result["agent_evaluation"]["agent_decision"]["review_process_ids"] == [2]
    assert result["agent_decisions"][-1]["changed_output"] is True
