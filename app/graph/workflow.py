# app/graph/workflow.py

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents.expert_executor import expert_executed_node
from app.agents.handoff import attach_agent_stage_outputs
from app.graph.node_worker import workerized_node
from app.graph.replan_node import should_continue_after_replan, should_replan
from app.graph.state import AXPlannerState


AGENT_STAGE_NODES: dict[str, list[str]] = {
    "context_evidence_agent": ["load_project_data", "retrieve_context"],
    "process_diagnosis_agent": ["process_analyzer", "data_readiness", "automation_feasibility"],
    "governance_compliance_agent": ["risk_governance", "compliance_assessment"],
    "business_case_agent": ["roi_cost", "priority_ranking"],
    "evaluation_critic_agent": ["agent_evaluator", "llm_critic"],
    "agent_replan": ["agent_replan"],
    "delivery_orchestration_agent": ["human_review", "poc_delivery_planner", "report_writer", "docx_generator"],
}

AGENT_STAGE_TO_AGENT_ID: dict[str, str] = {
    "context_evidence_agent": "context_evidence_agent",
    "process_diagnosis_agent": "process_diagnosis_agent",
    "governance_compliance_agent": "governance_compliance_agent",
    "business_case_agent": "business_case_agent",
    "evaluation_critic_agent": "evaluation_critic_agent",
    "agent_replan": "evaluation_critic_agent",
    "delivery_orchestration_agent": "delivery_orchestration_agent",
}


def merge_stage_result(accumulator: dict[str, Any], node_result: dict[str, Any]) -> dict[str, Any]:
    """Merge internal node outputs inside an Agent-stage node.

    LangGraph reducers merge across graph nodes, but here several old nodes run
    inside one Agent node. Preserve list-like trace fields instead of replacing
    them with the last internal node's value.
    """
    merged = dict(accumulator)
    list_keys = {
        "audit_logs",
        "errors",
        "agent_contracts",
        "agent_tool_calls",
        "agent_decisions",
        "agent_loop_iterations",
        "agent_loop_requests",
        "agent_supervisor_steps",
        "agent_handoffs",
    }
    for key, value in node_result.items():
        if key in list_keys:
            merged[key] = list(merged.get(key, [])) + list(value or [])
        else:
            merged[key] = value
    return merged


def latest_loop_index(result: dict[str, Any]) -> int | None:
    iterations = result.get("agent_loop_iterations") or []
    if not iterations:
        return None
    return iterations[-1].get("loop_index")


def expert_agent_stage(stage_name: str):
    """Create one LangGraph node for one Expert Agent.

    The top-level graph now moves by Agent stage. Each Agent stage runs the old
    tool-level nodes it owns, produces a package, then hands it off to the next
    Agent stage through explicit metadata.
    """
    internal_nodes = AGENT_STAGE_NODES[stage_name]
    agent_id = AGENT_STAGE_TO_AGENT_ID[stage_name]
    internal_runners = [
        (node_name, expert_executed_node(node_name, workerized_node(node_name)))
        for node_name in internal_nodes
    ]

    def _agent_node(state: dict[str, Any]) -> dict[str, Any]:
        stage_state = dict(state)
        stage_result: dict[str, Any] = {}
        executed_nodes: list[str] = []

        for node_name, runner in internal_runners:
            node_result = runner(stage_state)
            stage_result = merge_stage_result(stage_result, node_result)
            stage_state = {**stage_state, **node_result}
            executed_nodes.append(node_name)

        return attach_agent_stage_outputs(
            state=state,
            result=stage_result,
            agent_id=agent_id,
            stage_name=stage_name,
            executed_nodes=executed_nodes,
            loop_index=latest_loop_index(stage_result),
        )

    _agent_node.__name__ = f"agent_stage_{stage_name}"
    return _agent_node


def build_ax_planner_graph():
    builder = StateGraph(AXPlannerState)

    builder.add_node("context_evidence_agent", expert_agent_stage("context_evidence_agent"))
    builder.add_node("process_diagnosis_agent", expert_agent_stage("process_diagnosis_agent"))
    builder.add_node("governance_compliance_agent", expert_agent_stage("governance_compliance_agent"))
    builder.add_node("business_case_agent", expert_agent_stage("business_case_agent"))
    builder.add_node("evaluation_critic_agent", expert_agent_stage("evaluation_critic_agent"))
    builder.add_node("agent_replan", expert_agent_stage("agent_replan"))
    builder.add_node("delivery_orchestration_agent", expert_agent_stage("delivery_orchestration_agent"))

    builder.add_edge(START, "context_evidence_agent")

    # Context/Evidence package is handed to both diagnostic and governance Agents.
    builder.add_edge("context_evidence_agent", "process_diagnosis_agent")
    builder.add_edge("context_evidence_agent", "governance_compliance_agent")

    # Business Case Agent waits for diagnosis and governance packages.
    builder.add_edge(
        ["process_diagnosis_agent", "governance_compliance_agent"],
        "business_case_agent",
    )

    # Evaluation & Critic Agent validates the ranked business-case package.
    builder.add_edge("business_case_agent", "evaluation_critic_agent")

    # If the critic requests evidence refresh, the Evaluation Agent performs a bounded replan
    # and hands control back to Context & Evidence. Otherwise, delivery starts.
    builder.add_conditional_edges(
        "evaluation_critic_agent",
        should_replan,
        {
            "agent_replan": "agent_replan",
            "human_review": "delivery_orchestration_agent",
        },
    )
    builder.add_conditional_edges(
        "agent_replan",
        should_continue_after_replan,
        {
            "retrieve_context": "context_evidence_agent",
            "human_review": "delivery_orchestration_agent",
        },
    )

    builder.add_edge("delivery_orchestration_agent", END)

    return builder.compile(checkpointer=InMemorySaver())
