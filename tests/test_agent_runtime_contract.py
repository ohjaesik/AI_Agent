from __future__ import annotations

from app.agents.runtime import (
    bind_agent_contract_to_result,
    build_agent_contract,
    get_agent_id_for_node,
    with_agent_contract,
)


def test_build_agent_contract_for_graph_node() -> None:
    contract = build_agent_contract("data_readiness")

    assert contract is not None
    assert contract["node_name"] == "data_readiness"
    assert contract["agent_id"] == "data_readiness_agent"
    assert contract["implementation"] == "deterministic_scoring"
    assert contract["contract_found"] is True
    assert "data_quality_check" in contract["controls"]


def test_node_to_agent_mapping_for_bootstrap_node() -> None:
    assert get_agent_id_for_node("process_discovery_agent") == "process_discovery_agent"
    assert get_agent_id_for_node("llm_critic") == "agent_evaluator_agent"


def test_bind_agent_contract_to_result_adds_contract_and_audit() -> None:
    result = bind_agent_contract_to_result(
        "roi_cost",
        {"roi_cost": {"summary": {"total_processes": 2}}, "audit_logs": []},
    )

    assert result["agent_contracts"][0]["agent_id"] == "roi_cost_agent"
    assert result["agent_contracts"][0]["implementation"] == "deterministic_calculation"
    assert result["audit_logs"][0]["status"] == "agent_contract_bound"
    assert result["audit_logs"][0]["payload"]["agent_id"] == "roi_cost_agent"


def test_with_agent_contract_wraps_node_result() -> None:
    def sample_node(state: dict) -> dict:
        return {"data_readiness": {"summary": {"total_processes": 1}}, "audit_logs": []}

    wrapped = with_agent_contract("data_readiness", sample_node)
    result = wrapped({})

    assert result["agent_contracts"][0]["agent_id"] == "data_readiness_agent"
    assert result["audit_logs"][0]["status"] == "agent_contract_bound"
