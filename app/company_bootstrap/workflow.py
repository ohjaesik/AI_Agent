# app/company_bootstrap/workflow.py

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents.expert_executor import expert_executed_node
from app.agents.handoff import attach_agent_flow_outputs
from app.agents.model_router import SUPERVISOR_AGENT_ID, select_agent_model
from app.agents.registry import get_agent_spec
from app.agents.runtime import build_agent_contract, get_agent_binding_for_node
from app.agents.supervisor_llm import build_supervisor_llm_call_record, run_supervisor_delegation_prompt
from app.company_bootstrap.nodes import (
    company_profile_agent_node,
    process_discovery_agent_node,
    source_ingestion_agent_node,
)
from app.company_bootstrap.state import BootstrapState


def supervisor_delegated_node(node_name: str, node_fn):
    node_runner = expert_executed_node(node_name, node_fn)
    binding = get_agent_binding_for_node(node_name) or {}
    contract = build_agent_contract(node_name) or {}
    agent_id = str(binding.get("agent_id") or contract.get("agent_id") or "unknown_agent")

    def _node(state: dict[str, Any]) -> dict[str, Any]:
        supervisor_assignment = select_agent_model(
            agent_id=SUPERVISOR_AGENT_ID,
            stage_name=node_name,
            call_kind="supervisor_delegation",
            state=state,
        )
        supervisor_delegation = run_supervisor_delegation_prompt(
            agent_spec=get_agent_spec(agent_id) or {"id": agent_id, "name": agent_id, **(contract or {})},
            stage_name=node_name,
            internal_nodes=[node_name],
            state=state,
            incoming_handoffs=state.get("agent_handoffs", []),
            loop_index=1,
            model_assignment=supervisor_assignment,
        )
        supervisor_delegation["loop_index"] = 1
        supervisor_call_record = build_supervisor_llm_call_record(supervisor_delegation)
        delegated_state = {
            **state,
            "current_supervisor_model_assignment": supervisor_assignment,
            "current_supervisor_delegation": supervisor_delegation,
            "supervisor_approval_policy": supervisor_delegation.get("human_approval_policy", {}),
        }

        result = node_runner(delegated_state)
        result["agent_model_decisions"] = list(result.get("agent_model_decisions", [])) + [supervisor_assignment]
        result["agent_supervisor_delegations"] = list(result.get("agent_supervisor_delegations", [])) + [supervisor_delegation]
        result["agent_llm_calls"] = list(result.get("agent_llm_calls", [])) + [supervisor_call_record]
        return attach_agent_flow_outputs(
            state=delegated_state,
            result=result,
            agent_id=agent_id,
            node_name=node_name,
            contract=contract,
            loop_index=(result.get("agent_loop_iterations") or [{}])[-1].get("loop_index"),
        )

    _node.__name__ = f"bootstrap_supervisor_delegated_{node_name}"
    return _node


def build_bootstrap_supervisor_graph():
    builder = StateGraph(BootstrapState)

    builder.add_node("company_profile_agent", supervisor_delegated_node("company_profile_agent", company_profile_agent_node))
    builder.add_node("source_ingestion_agent", supervisor_delegated_node("source_ingestion_agent", source_ingestion_agent_node))
    builder.add_node("process_discovery_agent", supervisor_delegated_node("process_discovery_agent", process_discovery_agent_node))

    builder.add_edge(START, "company_profile_agent")
    builder.add_edge("company_profile_agent", "source_ingestion_agent")
    builder.add_edge("source_ingestion_agent", "process_discovery_agent")
    builder.add_edge("process_discovery_agent", END)

    return builder.compile(checkpointer=InMemorySaver())
