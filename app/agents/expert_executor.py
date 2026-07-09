# app/agents/expert_executor.py

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any, TypeVar

from app.agents.registry import get_agent_spec, get_tool_specs_for_node
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
        "replan_attempts": state.get("replan_attempts", 0),
        "available_state_keys": sorted(state.keys()),
    }


def tool_names(tool_specs: list[dict[str, Any]]) -> list[str]:
    return [str(item.get("name")) for item in tool_specs if item.get("name")]


def select_tool_spec(
    *,
    node_name: str,
    agent_spec: dict[str, Any],
    contract: dict[str, Any],
    candidate_tool_specs: list[dict[str, Any]],
    state: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    if not candidate_tool_specs:
        raise ValueError(f"No candidate tool specs for node: {node_name}")

    by_name = {str(item.get("name")): item for item in candidate_tool_specs}
    evaluation_summary = (state.get("agent_evaluation") or {}).get("summary", {}) or {}
    additional_evidence_count = int(evaluation_summary.get("additional_evidence_required_count", 0) or 0)
    priority_items = (state.get("priority_ranking") or {}).get("items", []) or []
    review_count = sum(1 for item in priority_items if item.get("status") == "human_review_required")
    blocked_count = sum(1 for item in priority_items if item.get("status") == "excluded")

    selection_rules = [
        (
            node_name == "priority_ranking" and (review_count > 0 or blocked_count > 0) and "candidate_status_calibrator" in by_name,
            "candidate_status_calibrator",
            "governance or review-required candidates exist, so the Business Case Agent selected a status calibration tool instead of only ranking by score.",
        ),
        (
            node_name == "agent_evaluator" and "evidence_replan_decider" in by_name,
            "evidence_replan_decider",
            "evaluation must decide whether weak evidence should trigger bounded replan or human review.",
        ),
        (
            node_name == "llm_critic" and additional_evidence_count > 0 and "critic_replan_decider" in by_name,
            "critic_replan_decider",
            "previous evaluation found evidence gaps, so the critic must produce a replan or human-review routing decision.",
        ),
        (
            node_name == "poc_delivery_planner" and review_count == len(priority_items) and priority_items and "poc_candidate_guard" in by_name,
            "poc_candidate_guard",
            "all candidates require review, so the Delivery Agent must guard PoC selection before planning.",
        ),
        (
            node_name == "report_writer" and state.get("agent_decisions") and "delivery_decision_summarizer" in by_name,
            "delivery_decision_summarizer",
            "previous Agent decisions exist and must be reflected in the final report data.",
        ),
    ]

    for condition, selected_name, reason in selection_rules:
        if condition:
            return by_name[selected_name], reason

    default_tool = candidate_tool_specs[0]
    return default_tool, (
        f"The {agent_spec.get('name')} selected the primary tool because node '{node_name}' "
        f"implements capability '{contract.get('capability')}' and no stronger routing condition was detected."
    )


def build_agent_tool_decision(
    *,
    node_name: str,
    agent_spec: dict[str, Any],
    contract: dict[str, Any],
    candidate_tool_specs: list[dict[str, Any]],
    selected_tool_spec: dict[str, Any],
    selection_reason: str,
    state: dict[str, Any],
) -> dict[str, Any]:
    return {
        "phase": "pre_tool_selection",
        "node_name": node_name,
        "agent_id": agent_spec.get("id"),
        "agent_name": agent_spec.get("name"),
        "capability": contract.get("capability"),
        "node_role": contract.get("node_role"),
        "candidate_tools": tool_names(candidate_tool_specs),
        "selected_tool": selected_tool_spec.get("name"),
        "tool_description": selected_tool_spec.get("description"),
        "selection_reason": selection_reason,
        "role_prompt": agent_spec.get("role_prompt", ""),
        "task_instructions": agent_spec.get("task_instructions", []),
        "state_summary": summarize_state_for_agent(state),
    }


def evidence_required_ids(agent_evaluation: dict[str, Any]) -> set[int]:
    ids: set[int] = set()
    for item in agent_evaluation.get("items", []) or []:
        if item.get("requires_additional_evidence") or item.get("predicted_status") == "evidence_insufficient":
            process_id = int(item.get("process_id") or 0)
            if process_id:
                ids.add(process_id)
    return ids


def count_llm_review_needs(agent_evaluation: dict[str, Any]) -> int:
    summary = agent_evaluation.get("summary", {}) or {}
    return int(summary.get("llm_critic_needs_review_count", 0) or 0)


def apply_priority_post_decision(result: dict[str, Any], decision: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    ranking = deepcopy(result.get("priority_ranking") or {})
    items = list(ranking.get("items", []) or [])
    adjusted_count = 0

    for item in items:
        if item.get("status") in {"excluded", "human_review_required"}:
            item["agent_decision_status"] = item.get("status")
            item["agent_decision_reason"] = "Business Case Agent preserved conservative governance/review status during ranking."
            adjusted_count += 1

    if adjusted_count:
        ranking["items"] = items
        ranking.setdefault("summary", {})["agent_decision_adjusted_count"] = adjusted_count
        ranking["summary"]["agent_decision_applied"] = True
        result["priority_ranking"] = ranking

    post_decision = {
        "phase": "post_tool_observation",
        "node_name": decision.get("node_name"),
        "agent_id": decision.get("agent_id"),
        "selected_tool": decision.get("selected_tool"),
        "decision": "preserve_review_status" if adjusted_count else "pass_through",
        "changed_output": bool(adjusted_count),
        "adjusted_count": adjusted_count,
        "reason": "Ranking results were checked against governance and human-review status.",
    }
    return result, post_decision


def apply_evaluation_post_decision(result: dict[str, Any], decision: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    evaluation = deepcopy(result.get("agent_evaluation") or {})
    ranking = deepcopy(result.get("priority_ranking") or {})
    summary = evaluation.setdefault("summary", {})
    required_ids = evidence_required_ids(evaluation)
    additional_count = int(summary.get("additional_evidence_required_count", 0) or 0)
    llm_review_count = count_llm_review_needs(evaluation)
    effective_required_count = max(additional_count, len(required_ids), llm_review_count)

    changed = False
    adjusted_count = 0
    if effective_required_count > 0:
        for item in ranking.get("items", []) or []:
            process_id = int(item.get("process_id") or 0)
            if process_id in required_ids or item.get("status") == "recommended":
                item.setdefault("status_before_agent_decision", item.get("status"))
                if process_id in required_ids:
                    item["status"] = "evidence_insufficient"
                    item["agent_decision_status"] = "replan_or_human_review_required"
                    item["agent_decision_reason"] = "Evaluation & Critic Agent detected insufficient evidence for this candidate."
                elif item.get("status") == "recommended":
                    item["status"] = "human_review_required"
                    item["agent_decision_status"] = "human_review_required"
                    item["agent_decision_reason"] = "Evaluation & Critic Agent required review before recommendation can be treated as final."
                adjusted_count += 1

        summary["additional_evidence_required_count"] = effective_required_count
        summary["agent_decision_adjusted_count"] = adjusted_count
        summary["agent_decision_applied"] = True
        evaluation["summary"] = summary
        evaluation["agent_decision"] = {
            "decision": "request_replan_or_human_review",
            "reason": "Evidence, confidence, or LLM critic review signals require a stronger routing decision before final PoC selection.",
            "target_process_ids": sorted(required_ids),
            "fallback_route": "human_review",
        }
        result["agent_evaluation"] = evaluation
        result["priority_ranking"] = ranking
        result.setdefault("replan_request", {})
        if not result["replan_request"]:
            result["replan_request"] = {
                "mode": "agent_decision_hint",
                "reason": "Evaluation & Critic Agent requested replan or human review after observing weak evidence/review signals.",
                "items": sorted(required_ids),
                "route_after_replan": "human_review",
            }
        changed = True

    post_decision = {
        "phase": "post_tool_observation",
        "node_name": decision.get("node_name"),
        "agent_id": decision.get("agent_id"),
        "selected_tool": decision.get("selected_tool"),
        "decision": "request_replan_or_human_review" if changed else "pass_through",
        "changed_output": changed,
        "adjusted_count": adjusted_count,
        "additional_evidence_required_count": effective_required_count,
        "reason": "The critic converts weak evidence and review observations into routing/status metadata.",
    }
    return result, post_decision


def apply_delivery_post_decision(result: dict[str, Any], decision: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    changed = False
    adjusted_count = 0
    node_name = str(decision.get("node_name"))

    if node_name == "poc_delivery_planner" and result.get("poc_plan"):
        poc_plan = deepcopy(result.get("poc_plan") or {})
        ranking_items = ((result.get("priority_ranking") or {}).get("items") or [])
        held_items = [item for item in ranking_items if item.get("status") in {"evidence_insufficient", "excluded"}]
        if held_items:
            poc_plan["agent_decision"] = {
                "decision": "guarded_poc_plan",
                "reason": "Some candidates were held by evaluation/governance, so PoC plan requires explicit review follow-up.",
                "held_candidate_count": len(held_items),
            }
            poc_plan["requires_governance_followup"] = True
            result["poc_plan"] = poc_plan
            changed = True
            adjusted_count = len(held_items)

    if node_name == "report_writer" and result.get("report_data"):
        report_data = deepcopy(result.get("report_data") or {})
        decisions = result.get("agent_decisions", []) or []
        report_data["agent_decision_summary"] = {
            "decision_count": len(decisions),
            "changed_output_count": sum(1 for item in decisions if item.get("changed_output")),
            "latest_decisions": decisions[-5:],
        }
        result["report_data"] = report_data
        changed = True

    post_decision = {
        "phase": "post_tool_observation",
        "node_name": node_name,
        "agent_id": decision.get("agent_id"),
        "selected_tool": decision.get("selected_tool"),
        "decision": "delivery_guard_applied" if changed else "pass_through",
        "changed_output": changed,
        "adjusted_count": adjusted_count,
        "reason": "Delivery Agent checked whether reviewed candidates can safely move into PoC/report output.",
    }
    return result, post_decision


def apply_post_decision(result: dict[str, Any], decision: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    node_name = str(decision.get("node_name"))
    mutable_result = deepcopy(result)

    if node_name == "priority_ranking":
        return apply_priority_post_decision(mutable_result, decision)
    if node_name in {"agent_evaluator", "llm_critic"}:
        return apply_evaluation_post_decision(mutable_result, decision)
    if node_name in {"poc_delivery_planner", "report_writer"}:
        return apply_delivery_post_decision(mutable_result, decision)

    return mutable_result, {
        "phase": "post_tool_observation",
        "node_name": node_name,
        "agent_id": decision.get("agent_id"),
        "selected_tool": decision.get("selected_tool"),
        "decision": "pass_through",
        "changed_output": False,
        "reason": "No post-tool adjustment rule was needed for this node.",
    }


def merge_agent_execution_result(
    *,
    node_name: str,
    base_result: dict[str, Any],
    contract: dict[str, Any],
    tool_audit_logs: list[dict[str, Any]],
    tool_observation: dict[str, Any],
    pre_decision: dict[str, Any],
    post_decision: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(base_result)
    existing_audit_logs = list(merged.get("audit_logs", []))
    merged["audit_logs"] = [
        *tool_audit_logs,
        *existing_audit_logs,
        build_contract_audit_log(node_name, {**contract, "selected_tool_spec": {"name": pre_decision.get("selected_tool")}}),
    ]
    merged["agent_contracts"] = list(merged.get("agent_contracts", [])) + [
        {
            **contract,
            "selected_tool": pre_decision.get("selected_tool"),
            "candidate_tools": pre_decision.get("candidate_tools", []),
            "tool_observation": tool_observation,
            "post_decision": post_decision,
        }
    ]
    merged["agent_tool_calls"] = list(merged.get("agent_tool_calls", [])) + [
        {
            "node_name": node_name,
            "agent_id": pre_decision.get("agent_id"),
            "capability": pre_decision.get("capability"),
            "candidate_tools": pre_decision.get("candidate_tools", []),
            "tool_name": pre_decision.get("selected_tool"),
            "tool_description": pre_decision.get("tool_description"),
            "selection_reason": pre_decision.get("selection_reason"),
            "observation": tool_observation,
        }
    ]
    merged["agent_decisions"] = list(merged.get("agent_decisions", [])) + [pre_decision, post_decision]
    return merged


def expert_executed_node(node_name: str, node_fn: Callable[[StateT], dict[str, Any]]) -> Callable[[StateT], dict[str, Any]]:
    """Run a graph node through an expert Agent with up to 3 candidate tools and post-decision calibration."""

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

        candidate_tool_specs = get_tool_specs_for_node(agent_id, node_name)
        if not candidate_tool_specs:
            raise ValueError(f"No tool_specs entry for agent '{agent_id}' and node '{node_name}'")
        if len(candidate_tool_specs) > 3:
            raise ValueError(f"Too many candidate tools for node '{node_name}': {len(candidate_tool_specs)}")

        selected_tool_spec, selection_reason = select_tool_spec(
            node_name=node_name,
            agent_spec=agent_spec,
            contract=contract,
            candidate_tool_specs=candidate_tool_specs,
            state=state,
        )

        pre_decision = build_agent_tool_decision(
            node_name=node_name,
            agent_spec=agent_spec,
            contract=contract,
            candidate_tool_specs=candidate_tool_specs,
            selected_tool_spec=selected_tool_spec,
            selection_reason=selection_reason,
            state=state,
        )

        tool_call = call_agent_tool(
            agent_id=agent_id,
            tool_name=str(selected_tool_spec["name"]),
            payload={"state": state, "agent_decision": pre_decision},
            runner=lambda payload: node_fn(payload["state"]),
            node_name=node_name,
        )

        post_processed_result, post_decision = apply_post_decision(tool_call.result, pre_decision)

        return merge_agent_execution_result(
            node_name=node_name,
            base_result=post_processed_result,
            contract={**contract, "candidate_tool_specs": candidate_tool_specs, "selected_tool_spec": selected_tool_spec},
            tool_audit_logs=tool_call.audit_logs,
            tool_observation=tool_call.observation,
            pre_decision=pre_decision,
            post_decision=post_decision,
        )

    _node.__name__ = f"expert_executed_{node_name}"
    return _node
