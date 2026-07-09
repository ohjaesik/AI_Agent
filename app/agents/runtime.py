# app/agents/runtime.py

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, TypeVar

from app.agents.registry import get_agent_spec

StateT = TypeVar("StateT", bound=dict[str, Any])

NODE_AGENT_MAP: dict[str, str] = {
    # Company bootstrap supervisor graph
    "company_profile_agent": "company_profile_agent",
    "source_ingestion_agent": "source_ingestion_agent",
    "process_discovery_agent": "process_discovery_agent",
    # Main AX planner graph
    "load_project_data": "company_profile_agent",
    "retrieve_context": "source_ingestion_agent",
    "process_analyzer": "process_analysis_agent",
    "data_readiness": "data_readiness_agent",
    "automation_feasibility": "automation_feasibility_agent",
    "roi_cost": "roi_cost_agent",
    "risk_governance": "risk_governance_agent",
    "compliance_assessment": "risk_governance_agent",
    "priority_ranking": "priority_delivery_agent",
    "agent_evaluator": "agent_evaluator_agent",
    "llm_critic": "agent_evaluator_agent",
    "agent_replan": "agent_evaluator_agent",
    "human_review": "priority_delivery_agent",
    "poc_delivery_planner": "priority_delivery_agent",
    "report_writer": "priority_delivery_agent",
    "docx_generator": "priority_delivery_agent",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_agent_id_for_node(node_name: str) -> str | None:
    return NODE_AGENT_MAP.get(node_name)


def build_agent_contract(node_name: str) -> dict[str, Any] | None:
    agent_id = get_agent_id_for_node(node_name)
    if not agent_id:
        return None

    spec = get_agent_spec(agent_id)
    if not spec:
        return {
            "node_name": node_name,
            "agent_id": agent_id,
            "agent_name": agent_id,
            "contract_found": False,
        }

    return {
        "node_name": node_name,
        "agent_id": spec["id"],
        "agent_name": spec["name"],
        "category": spec["category"],
        "implementation": spec["implementation"],
        "inputs": list(spec.get("inputs", [])),
        "outputs": list(spec.get("outputs", [])),
        "tools": list(spec.get("tools", [])),
        "controls": list(spec.get("controls", [])),
        "human_review_required": bool(spec.get("human_review_required", False)),
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
