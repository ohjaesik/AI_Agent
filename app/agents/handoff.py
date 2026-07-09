# app/agents/handoff.py

from __future__ import annotations

from typing import Any

SUPERVISOR_AGENT_ID = "ax_delivery_supervisor_agent"
SUPERVISOR_AGENT_NAME = "AX Delivery Supervisor Agent"

AGENT_STAGE_ORDER = [
    "context_evidence_agent",
    "process_diagnosis_agent",
    "governance_compliance_agent",
    "business_case_agent",
    "evaluation_critic_agent",
    "delivery_orchestration_agent",
]

AGENT_TO_PACKAGE = {
    "context_evidence_agent": "context_evidence_package",
    "process_diagnosis_agent": "process_diagnosis_package",
    "governance_compliance_agent": "governance_package",
    "business_case_agent": "business_case_package",
    "evaluation_critic_agent": "evaluation_package",
    "delivery_orchestration_agent": "delivery_package",
}

NODE_TO_PACKAGE = {
    "load_project_data": "context_evidence_package",
    "retrieve_context": "context_evidence_package",
    "process_analyzer": "process_diagnosis_package",
    "data_readiness": "process_diagnosis_package",
    "automation_feasibility": "process_diagnosis_package",
    "risk_governance": "governance_package",
    "compliance_assessment": "governance_package",
    "roi_cost": "business_case_package",
    "priority_ranking": "business_case_package",
    "agent_evaluator": "evaluation_package",
    "llm_critic": "evaluation_package",
    "agent_replan": "evaluation_package",
    "human_review": "delivery_package",
    "poc_delivery_planner": "delivery_package",
    "report_writer": "delivery_package",
    "docx_generator": "delivery_package",
}

AGENT_OUTPUT_KEYS = {
    "context_evidence_agent": [
        "project",
        "company_profile",
        "business_processes",
        "documents",
        "retrieved_contexts",
        "evidence_items",
        "used_sources",
    ],
    "process_diagnosis_agent": [
        "process_analysis",
        "data_readiness",
        "automation_feasibility",
    ],
    "governance_compliance_agent": [
        "risk_governance",
        "compliance_assessment",
    ],
    "business_case_agent": [
        "roi_cost",
        "priority_ranking",
    ],
    "evaluation_critic_agent": [
        "agent_evaluation",
        "priority_ranking",
        "replan_request",
    ],
    "delivery_orchestration_agent": [
        "human_review",
        "poc_plan",
        "report_data",
        "report_docx_path",
    ],
}

AGENT_INPUT_KEYS = {
    "context_evidence_agent": ["project_id", "company_id", "replan_request"],
    "process_diagnosis_agent": ["business_processes", "retrieved_contexts", "evidence_items"],
    "governance_compliance_agent": ["business_processes", "retrieved_contexts", "evidence_items"],
    "business_case_agent": [
        "process_analysis",
        "data_readiness",
        "automation_feasibility",
        "risk_governance",
        "compliance_assessment",
    ],
    "evaluation_critic_agent": ["priority_ranking", "roi_cost", "evidence_items", "used_sources"],
    "delivery_orchestration_agent": ["priority_ranking", "agent_evaluation", "human_review"],
}

HANDOFF_RULES = {
    "context_evidence_agent": [
        {
            "to_agent": "process_diagnosis_agent",
            "target_nodes": ["process_analyzer", "data_readiness", "automation_feasibility"],
            "payload_keys": ["business_processes", "retrieved_contexts", "evidence_items"],
            "reason": "Process Diagnosis Agent needs business-process context and traceable RAG evidence.",
        },
        {
            "to_agent": "governance_compliance_agent",
            "target_nodes": ["risk_governance", "compliance_assessment"],
            "payload_keys": ["business_processes", "retrieved_contexts", "evidence_items", "used_sources"],
            "reason": "Governance & Compliance Agent needs process context and source-grounded evidence for risk screening.",
        },
    ],
    "process_diagnosis_agent": [
        {
            "to_agent": "business_case_agent",
            "target_nodes": ["roi_cost", "priority_ranking"],
            "payload_keys": ["process_analysis", "data_readiness", "automation_feasibility"],
            "reason": "Business Case Agent needs diagnosis, readiness, and feasibility outputs to calculate ROI and rank candidates.",
        }
    ],
    "governance_compliance_agent": [
        {
            "to_agent": "business_case_agent",
            "target_nodes": ["priority_ranking"],
            "payload_keys": ["risk_governance", "compliance_assessment"],
            "reason": "Business Case Agent must include governance and compliance signals before ranking.",
        }
    ],
    "business_case_agent": [
        {
            "to_agent": "evaluation_critic_agent",
            "target_nodes": ["agent_evaluator", "llm_critic"],
            "payload_keys": ["roi_cost", "priority_ranking"],
            "reason": "Evaluation & Critic Agent must validate ranked candidates before delivery.",
        }
    ],
    "evaluation_critic_agent": [
        {
            "to_agent": "context_evidence_agent",
            "target_nodes": ["load_project_data", "retrieve_context"],
            "payload_keys": ["replan_request", "agent_evaluation"],
            "reason": "Evidence gaps require bounded re-query and evidence refresh.",
            "condition": "replan_request_present",
        },
        {
            "to_agent": "delivery_orchestration_agent",
            "target_nodes": ["human_review", "poc_delivery_planner", "report_writer", "docx_generator"],
            "payload_keys": ["priority_ranking", "agent_evaluation"],
            "reason": "Delivery Orchestration Agent receives validated candidates and human-review requirements.",
        },
    ],
    "delivery_orchestration_agent": [
        {
            "to_agent": "final_output",
            "target_nodes": [],
            "payload_keys": ["human_review", "poc_plan", "report_data", "report_docx_path"],
            "reason": "Final delivery package is ready for artifact export.",
        }
    ],
}


def present_keys(state: dict[str, Any], keys: list[str]) -> list[str]:
    return [key for key in keys if state.get(key) not in (None, {}, [])]


def should_emit_rule(rule: dict[str, Any], state: dict[str, Any]) -> bool:
    condition = rule.get("condition")
    if condition == "replan_request_present":
        return bool(state.get("replan_request"))
    return True


def build_agent_package(agent_id: str, state: dict[str, Any], produced_by: str, executed_nodes: list[str] | None = None) -> dict[str, Any]:
    output_keys = AGENT_OUTPUT_KEYS.get(agent_id, [])
    return {
        "agent_id": agent_id,
        "produced_by": produced_by,
        "executed_nodes": executed_nodes or [],
        "output_keys": present_keys(state, output_keys),
        "input_keys_consumed": present_keys(state, AGENT_INPUT_KEYS.get(agent_id, [])),
        "summary": {
            "business_processes": len(state.get("business_processes", []) or []),
            "evidence_items": len(state.get("evidence_items", []) or []),
            "used_sources": len(state.get("used_sources", []) or []),
            "priority_candidates": len((state.get("priority_ranking", {}) or {}).get("items", []) or []),
            "has_replan_request": bool(state.get("replan_request")),
            "has_human_review": bool(state.get("human_review")),
            "has_report_data": bool(state.get("report_data")),
            "has_docx": bool(state.get("report_docx_path")),
        },
    }


def build_supervisor_step(
    agent_id: str,
    stage_name: str,
    state: dict[str, Any],
    contract: dict[str, Any] | None = None,
    executed_nodes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "supervisor_agent_id": SUPERVISOR_AGENT_ID,
        "supervisor_agent_name": SUPERVISOR_AGENT_NAME,
        "delegated_to": agent_id,
        "delegated_stage": stage_name,
        "delegated_nodes": executed_nodes or [],
        "capability": (contract or {}).get("capability"),
        "task": (contract or {}).get("node_role") or f"Run {agent_id} stage and produce handoff package.",
        "input_keys": present_keys(state, AGENT_INPUT_KEYS.get(agent_id, [])),
        "expected_output_keys": AGENT_OUTPUT_KEYS.get(agent_id, []),
        "reason": f"{SUPERVISOR_AGENT_NAME} delegated this stage to {agent_id} and expects a package for downstream Agents.",
    }


def build_handoffs(
    agent_id: str,
    stage_name: str,
    state: dict[str, Any],
    loop_index: int | None = None,
    executed_nodes: list[str] | None = None,
) -> list[dict[str, Any]]:
    handoffs: list[dict[str, Any]] = []
    for rule in HANDOFF_RULES.get(agent_id, []):
        if not should_emit_rule(rule, state):
            continue
        handoffs.append(
            {
                "from_agent": agent_id,
                "to_agent": rule["to_agent"],
                "source_stage": stage_name,
                "source_nodes": executed_nodes or [],
                "target_nodes": rule.get("target_nodes", []),
                "payload_keys": present_keys(state, rule.get("payload_keys", [])),
                "declared_payload_keys": rule.get("payload_keys", []),
                "handoff_reason": rule.get("reason"),
                "loop_index": loop_index,
            }
        )
    return handoffs


def attach_agent_flow_outputs(
    *,
    state: dict[str, Any],
    result: dict[str, Any],
    agent_id: str,
    node_name: str,
    contract: dict[str, Any],
    loop_index: int | None = None,
) -> dict[str, Any]:
    merged_state = {**state, **result}
    package_key = NODE_TO_PACKAGE.get(node_name) or AGENT_TO_PACKAGE.get(agent_id)
    supervisor_step = build_supervisor_step(agent_id, node_name, merged_state, contract, executed_nodes=[node_name])
    handoffs = build_handoffs(agent_id, node_name, merged_state, loop_index=loop_index, executed_nodes=[node_name])

    output = dict(result)
    output["agent_supervisor_steps"] = list(output.get("agent_supervisor_steps", [])) + [supervisor_step]
    if handoffs:
        output["agent_handoffs"] = list(output.get("agent_handoffs", [])) + handoffs
    if package_key:
        output[package_key] = build_agent_package(agent_id, merged_state, node_name, executed_nodes=[node_name])
    return output


def attach_agent_stage_outputs(
    *,
    state: dict[str, Any],
    result: dict[str, Any],
    agent_id: str,
    stage_name: str,
    executed_nodes: list[str],
    loop_index: int | None = None,
) -> dict[str, Any]:
    merged_state = {**state, **result}
    package_key = AGENT_TO_PACKAGE.get(agent_id)
    supervisor_step = build_supervisor_step(agent_id, stage_name, merged_state, executed_nodes=executed_nodes)
    handoffs = build_handoffs(agent_id, stage_name, merged_state, loop_index=loop_index, executed_nodes=executed_nodes)

    output = dict(result)
    output["agent_supervisor_steps"] = list(output.get("agent_supervisor_steps", [])) + [supervisor_step]
    if handoffs:
        output["agent_handoffs"] = list(output.get("agent_handoffs", [])) + handoffs
    if package_key:
        output[package_key] = build_agent_package(agent_id, merged_state, stage_name, executed_nodes=executed_nodes)
    return output
