# app/graph/workflow.py

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents.expert_executor import expert_executed_node
from app.agents.handoff import attach_agent_flow_outputs
from app.agents.runtime import build_agent_contract, get_agent_binding_for_node
from app.graph.node_worker import workerized_node
from app.graph.replan_node import should_continue_after_replan, should_replan
from app.graph.state import AXPlannerState


def supervisor_delegated_node(node_name: str):
    """Wrap a LangGraph node as an Agent-to-Agent delegated task.

    The graph still executes deterministic node edges, but every node result now
    carries explicit Supervisor delegation, Agent package, and handoff metadata so
    the runtime trace reads as Agent -> Agent flow instead of bare node chaining.
    """
    node_runner = expert_executed_node(node_name, workerized_node(node_name))
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

    _node.__name__ = f"supervisor_delegated_{node_name}"
    return _node


def build_ax_planner_graph():
    builder = StateGraph(AXPlannerState)

    builder.add_node("load_project_data", supervisor_delegated_node("load_project_data"))
    builder.add_node("retrieve_context", supervisor_delegated_node("retrieve_context"))
    builder.add_node("process_analyzer", supervisor_delegated_node("process_analyzer"))
    builder.add_node("data_readiness", supervisor_delegated_node("data_readiness"))
    builder.add_node("automation_feasibility", supervisor_delegated_node("automation_feasibility"))
    builder.add_node("roi_cost", supervisor_delegated_node("roi_cost"))
    builder.add_node("risk_governance", supervisor_delegated_node("risk_governance"))
    builder.add_node("compliance_assessment", supervisor_delegated_node("compliance_assessment"))
    builder.add_node("priority_ranking", supervisor_delegated_node("priority_ranking"))
    builder.add_node("agent_evaluator", supervisor_delegated_node("agent_evaluator"))
    builder.add_node("llm_critic", supervisor_delegated_node("llm_critic"))
    builder.add_node("agent_replan", supervisor_delegated_node("agent_replan"))
    builder.add_node("human_review", supervisor_delegated_node("human_review"))
    builder.add_node("poc_delivery_planner", supervisor_delegated_node("poc_delivery_planner"))
    builder.add_node("report_writer", supervisor_delegated_node("report_writer"))
    builder.add_node("docx_generator", supervisor_delegated_node("docx_generator"))

    # 공통 입력 로드 단계
    builder.add_edge(START, "load_project_data")
    builder.add_edge("load_project_data", "retrieve_context")

    # 병렬 분석 fan-out
    builder.add_edge("retrieve_context", "process_analyzer")
    builder.add_edge("retrieve_context", "data_readiness")
    builder.add_edge("retrieve_context", "automation_feasibility")
    builder.add_edge("retrieve_context", "risk_governance")

    # 부분 의존성
    builder.add_edge("automation_feasibility", "roi_cost")
    builder.add_edge("risk_governance", "compliance_assessment")

    # fan-in: 모든 핵심 분석 결과가 준비된 뒤 우선순위 산정
    builder.add_edge(
        [
            "process_analyzer",
            "data_readiness",
            "roi_cost",
            "compliance_assessment",
        ],
        "priority_ranking",
    )

    # Agent Evaluator + LLM Critic이 추천 결과의 근거 coverage, confidence, compliance alignment를 재검증한다.
    builder.add_edge("priority_ranking", "agent_evaluator")
    builder.add_edge("agent_evaluator", "llm_critic")

    # 근거 부족 후보가 있으면 제한된 횟수만 RAG re-query loop를 수행하고, 초과/무효 시 Human Review로 넘긴다.
    builder.add_conditional_edges(
        "llm_critic",
        should_replan,
        {
            "agent_replan": "agent_replan",
            "human_review": "human_review",
        },
    )
    builder.add_conditional_edges(
        "agent_replan",
        should_continue_after_replan,
        {
            "retrieve_context": "retrieve_context",
            "human_review": "human_review",
        },
    )

    # 의사결정 및 산출물 생성 단계
    builder.add_edge("human_review", "poc_delivery_planner")
    builder.add_edge("poc_delivery_planner", "report_writer")
    builder.add_edge("report_writer", "docx_generator")
    builder.add_edge("docx_generator", END)

    checkpointer = InMemorySaver()

    return builder.compile(checkpointer=checkpointer)
