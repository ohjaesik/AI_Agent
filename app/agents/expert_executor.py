# app/agents/expert_executor.py

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from app.agents.registry import get_agent_spec, get_tool_spec_for_node
from app.agents.runtime import build_agent_contract, build_contract_audit_log, get_agent_binding_for_node
from app.agents.tool_runtime import call_agent_tool

StateT = TypeVar("StateT", bound=dict[str, Any])


def summarize_state_for_agent(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_id": state.get("project_id"),
        "company_id": state.get("company_id"),
        "user_request": state.get("user_request"),
        "business_process_count": len(state.get("business_processes", []) or []),
        "document_count": len(state.get("documents", []) or []),
        "evidence_item_count": len(state.get("evidence_items", []) or []),
        "used_source_count": len(state.get("used_sources", []) or []),
        "priority_item_count": len((state.get("priority_ranking", {}) or {}).get("items", []) or []),
        "has_human_review": bool(state.get("human_review")),
        "available_state_keys": sorted(state.keys()),
    }


def build_agent_tool_decision(
    *,
    node_name: str,
    agent_spec: dict[str, Any],
    contract: dict[str, Any],
    tool_spec: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    return {
        "node_name": node_name,
        "agent_id": agent_spec.get("id"),
        "agent_name": agent_spec.get("name"),
        "capability": contract.get("capability"),
        "node_role": contract.get("node_role"),
        "selected_tool": tool_spec.get("name"),
        "tool_description": tool_spec.get("description"),
        "selection_reason": (
            f"The {agent_spec.get('name')} selected {tool_spec.get('name')} because node '{node_name}' "
            f"implements capability '{contract.get('capability')}'."
        ),
        "role_prompt": agent_spec.get("role_prompt", ""),
        "task_instructions": agent_spec.get("task_instructions", []),
        "state_summary": summarize_state_for_agent(state),
    }


def merge_agent_execution_result(
    *,
    node_name: str,
    base_result: dict[str, Any],
    contract: dict[str, Any],
    tool_audit_logs: list[dict[str, Any]],
    tool_observation: dict[str, Any],
    decision: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(base_result)
    existing_audit_logs = list(merged.get("audit_logs", []))
    merged["audit_logs"] = [
        *tool_audit_logs,
        *existing_audit_logs,
        build_contract_audit_log(node_name, contract),
    ]
    merged["agent_contracts"] = list(merged.get("agent_contracts", [])) + [
        {
            **contract,
            "selected_tool": decision.get("selected_tool"),
            "tool_observation": tool_observation,
        }
    ]
    merged["agent_tool_calls"] = list(merged.get("agent_tool_calls", [])) + [
        {
            "node_name": node_name,
            "agent_id": decision.get("agent_id"),
            "capability": decision.get("capability"),
            "tool_name": decision.get("selected_tool"),
            "tool_description": decision.get("tool_description"),
            "selection_reason": decision.get("selection_reason"),
            "observation": tool_observation,
        }
    ]
    return merged


def expert_executed_node(node_name: str, node_fn: Callable[[StateT], dict[str, Any]]) -> Callable[[StateT], dict[str, Any]]:
    """Wrap a graph node so an expert Agent chooses and calls the bound tool.

    This replaces direct node execution with:
    Agent contract -> capability -> selected tool -> permission check -> tool run -> observation/audit.
    """
    def _node(state: StateT) -> dict[str, Any]:
        binding = get_agent_binding_for_node(node_name)
        if not binding:
            return node_fn(state)

        agent_id = binding["agent_id"]
        agent_spec = get_agent_spec(agent_id)
        if not agent_spec:
            raise ValueError(f"Unknown agent_id for node '{node_name}': {agent_id}")

        contract = build_agent_contract(node_name)
        if not contract:
            raise ValueError(f"No agent contract for node: {node_name}")

        tool_spec = get_tool_spec_for_node(agent_id, node_name)
        if not tool_spec:
            raise ValueError(f"No tool_specs entry for agent '{agent_id}' and node '{node_name}'")

        decision = build_agent_tool_decision(
            node_name=node_name,
            agent_spec=agent_spec,
            contract=contract,
            tool_spec=tool_spec,
            state=state,
        )

        tool_call = call_agent_tool(
            agent_id=agent_id,
            tool_name=str(tool_spec["name"]),
            payload={"state": state, "agent_decision": decision},
            runner=lambda payload: node_fn(payload["state"]),
            node_name=node_name,
        )

        return merge_agent_execution_result(
            node_name=node_name,
            base_result=tool_call.result,
            contract=contract,
            tool_audit_logs=tool_call.audit_logs,
            tool_observation=tool_call.observation,
            decision=decision,
        )

    _node.__name__ = f"expert_executed_{node_name}"
    return _node
