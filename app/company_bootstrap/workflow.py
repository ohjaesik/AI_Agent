# app/company_bootstrap/workflow.py

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents.expert_executor import expert_executed_node
from app.agents.handoff import attach_agent_flow_outputs
from app.agents.runtime import build_agent_contract, get_agent_binding_for_node
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
        result = node_runner(state)
        return attach_agent_flow_outputs(
            state=state,
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
