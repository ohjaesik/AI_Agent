# app/graph/workflow.py

from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents.runtime import with_agent_contract
from app.graph.node_worker import workerized_node
from app.graph.replan_node import should_continue_after_replan, should_replan
from app.graph.state import AXPlannerState


def contract_bound_workerized_node(node_name: str):
    return with_agent_contract(node_name, workerized_node(node_name))


def build_ax_planner_graph():
    builder = StateGraph(AXPlannerState)

    builder.add_node("load_project_data", contract_bound_workerized_node("load_project_data"))
    builder.add_node("retrieve_context", contract_bound_workerized_node("retrieve_context"))
    builder.add_node("process_analyzer", contract_bound_workerized_node("process_analyzer"))
    builder.add_node("data_readiness", contract_bound_workerized_node("data_readiness"))
    builder.add_node("automation_feasibility", contract_bound_workerized_node("automation_feasibility"))
    builder.add_node("roi_cost", contract_bound_workerized_node("roi_cost"))
    builder.add_node("risk_governance", contract_bound_workerized_node("risk_governance"))
    builder.add_node("compliance_assessment", contract_bound_workerized_node("compliance_assessment"))
    builder.add_node("priority_ranking", contract_bound_workerized_node("priority_ranking"))
    builder.add_node("agent_evaluator", contract_bound_workerized_node("agent_evaluator"))
    builder.add_node("llm_critic", contract_bound_workerized_node("llm_critic"))
    builder.add_node("agent_replan", contract_bound_workerized_node("agent_replan"))
    builder.add_node("human_review", contract_bound_workerized_node("human_review"))
    builder.add_node("poc_delivery_planner", contract_bound_workerized_node("poc_delivery_planner"))
    builder.add_node("report_writer", contract_bound_workerized_node("report_writer"))
    builder.add_node("docx_generator", contract_bound_workerized_node("docx_generator"))

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
