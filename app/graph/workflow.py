# app/graph/workflow.py

from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.graph.nodes import (
    automation_feasibility_node,
    data_readiness_node,
    docx_generator_node,
    human_review_node,
    load_project_data_node,
    poc_delivery_planner_node,
    priority_ranking_node,
    process_analyzer_node,
    report_writer_node,
    retrieve_context_node,
    risk_governance_node,
    roi_cost_node,
)
from app.graph.state import AXPlannerState


def build_ax_planner_graph():
    builder = StateGraph(AXPlannerState)

    builder.add_node("load_project_data", load_project_data_node)
    builder.add_node("retrieve_context", retrieve_context_node)
    builder.add_node("process_analyzer", process_analyzer_node)
    builder.add_node("data_readiness", data_readiness_node)
    builder.add_node("automation_feasibility", automation_feasibility_node)
    builder.add_node("roi_cost", roi_cost_node)
    builder.add_node("risk_governance", risk_governance_node)
    builder.add_node("priority_ranking", priority_ranking_node)
    builder.add_node("human_review", human_review_node)
    builder.add_node("poc_delivery_planner", poc_delivery_planner_node)
    builder.add_node("report_writer", report_writer_node)
    builder.add_node("docx_generator", docx_generator_node)

    builder.add_edge(START, "load_project_data")
    builder.add_edge("load_project_data", "retrieve_context")
    builder.add_edge("retrieve_context", "process_analyzer")
    builder.add_edge("process_analyzer", "data_readiness")
    builder.add_edge("data_readiness", "automation_feasibility")
    builder.add_edge("automation_feasibility", "roi_cost")
    builder.add_edge("roi_cost", "risk_governance")
    builder.add_edge("risk_governance", "priority_ranking")
    builder.add_edge("priority_ranking", "human_review")
    builder.add_edge("human_review", "poc_delivery_planner")
    builder.add_edge("poc_delivery_planner", "report_writer")
    builder.add_edge("report_writer", "docx_generator")
    builder.add_edge("docx_generator", END)

    checkpointer = InMemorySaver()

    return builder.compile(checkpointer=checkpointer)