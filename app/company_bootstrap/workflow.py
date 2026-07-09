# app/company_bootstrap/workflow.py

from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents.runtime import with_agent_contract
from app.company_bootstrap.nodes import (
    company_profile_agent_node,
    process_discovery_agent_node,
    source_ingestion_agent_node,
)
from app.company_bootstrap.state import BootstrapState


def build_bootstrap_supervisor_graph():
    builder = StateGraph(BootstrapState)

    builder.add_node("company_profile_agent", with_agent_contract("company_profile_agent", company_profile_agent_node))
    builder.add_node("source_ingestion_agent", with_agent_contract("source_ingestion_agent", source_ingestion_agent_node))
    builder.add_node("process_discovery_agent", with_agent_contract("process_discovery_agent", process_discovery_agent_node))

    builder.add_edge(START, "company_profile_agent")
    builder.add_edge("company_profile_agent", "source_ingestion_agent")
    builder.add_edge("source_ingestion_agent", "process_discovery_agent")
    builder.add_edge("process_discovery_agent", END)

    return builder.compile(checkpointer=InMemorySaver())
