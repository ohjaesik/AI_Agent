# app/agents/expert_executor.py

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any, TypeVar

from app.agents.llm_planner import plan_agent_post_decision, plan_agent_tool_selection
from app.agents.registry import get_agent_spec, get_tool_specs_for_node
from app.agents.runtime import build_agent_contract, build_contract_audit_log, get_agent_binding_for_node
from app.agents.tool_runtime import call_agent_tool

StateT = TypeVar("StateT", bound=dict[str, Any])

EVIDENCE_INSUFFICIENT_THRESHOLD = 0.15
LOW_CONFIDENCE_THRESHOLD = 0.45


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


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def select_tool_spec(
    *,
    node_name: str,
    agent_spec: dict[str, Any],
    contract: dict[str, Any],
    candidate_tool_specs: list[dict[str, Any]],
    state: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    """Deterministic fallback selector.

    The Expert Agent first receives these assigned candidates from AgentSpec.tool_specs.
    The LLM planner may choose another assigned candidate, but never a tool outside this list.
    """
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
            "governance or review-required candidates exist, so deterministic fallback selected a status calibration tool instead of only ranking by score.",
        ),
        (
            node_name == "agent_evaluator" and "evidence_replan_decider" in by_name,
            "evidence_replan_decider",
            "evaluation must decide whether weak evidence should trigger bounded replan or human review.",
        ),
        (
            node_name == "llm_critic" and additional_evidence_count > 0 and "critic_replan_decider" in by_name,
            "critic_replan_decider",
            "previous evaluation found evidence gaps, so deterministic fallback selected a replan/human-review routing tool.",
        ),
        (
            node_name == "poc_delivery_planner" and review_count == len(priority_items) and priority_items and "poc_candidate_guard" in by_name,
            "poc_candidate_guard",
            "all candidates require review, so deterministic fallback selected a PoC selection guard.",
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
        f"The {agent_spec.get('name')} fallback policy selected the primary assigned tool because node '{node_name}' "
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
    planner_result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "phase": "pre_tool_selection",
        "node_name": node_name,
        "agent_id": agent_spec.get("id"),
        "agent_name": agent_spec.get("name"),
        "capability": contract.get("capability"),
        "node_role": contract.get("node_role"),
        "candidate_tools": tool_names(candidate_tool_specs),
        "assigned_tools": planner_result.get("assigned_tools", []),
        "selected_tool": selected_tool_spec.get("name"),
        "selected_tool_uses_llm": bool(planner_result.get("selected_tool_uses_llm")),
        "tool_description": selected_tool_spec.get("description"),
        "selection_reason": selection_reason,
        "planner_mode": planner_result.get("planner_mode"),
        "planner_used_llm": bool(planner_result.get("planner_used_llm")),
        "planner_risk_note": planner_result.get("risk_note"),
        "role_prompt": agent_spec.get("role_prompt", ""),
        "task_instructions": agent_spec.get("task_instructions", []),
        "state_summary": summarize_state_for_agent(state),
    }


def split_evidence_decision_ids(agent_evaluation: dict[str, Any]) -> tuple[set[int], set[int]]:
    """Split severe evidence-insufficient candidates from ordinary review cases."""
    insufficient_ids: set[int] = set()
    review_ids: set[int] = set()

    for item in agent_evaluation.get("items", []) or []:
        process_id = int(item.get("process_id") or 0)
        if not process_id:
            continue

        evidence_coverage = as_float(item.get("evidence_coverage"), 0.0)
        confidence_score = as_float(item.get("confidence_score"), 0.0)
        predicted_status = str(item.get("predicted_status") or "")
        requires_additional_evidence = bool(item.get("requires_additional_evidence"))
        requires_human_review = bool(item.get("requires_human_review"))
        critic = item.get("llm_critic") or {}
        critic_verdict = str(critic.get("critic_verdict") or "")

        severe_evidence_gap = evidence_coverage <= EVIDENCE_INSUFFICIENT_THRESHOLD
        severe_low_confidence = confidence_score < LOW_CONFIDENCE_THRESHOLD
        explicit_insufficient = predicted_status == "evidence_insufficient"

        if severe_evidence_gap or (explicit_insufficient and severe_low_confidence):
            insufficient_ids.add(process_id)
        elif requires_additional_evidence or requires_human_review or explicit_insufficient or critic_verdict in {"needs_review", "revise"}:
            review_ids.add(process_id)

    review_ids -= insufficient_ids
    return insufficient_ids, review_ids


def count_llm_review_needs(agent_evaluation: dict[str, Any]) -> int:
    summary = agent_evaluation.get("summary", {}) or {}
    return int(summary.get("llm_critic_needs_review_count", 0) or 0)


def rebuild_priority_summary(ranking: dict[str, Any]) -> dict[str, Any]:
    items = ranking.get("items", []) or []
    status_counts: dict[str, int] = {}
    for item in items:
        status = str(item.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    summary = dict(ranking.get("summary", {}) or {})
    summary.update(
        {
            "total_candidates": len(items),
            "recommended_count": status_counts.get("recommended", 0),
            "review_required_count": status_counts.get("human_review_required", 0),
            "human_review_required_count": status_counts.get("human_review_required", 0),
            "evidence_insufficient_count": status_counts.get("evidence_insufficient", 0),
            "excluded_count": status_counts.get("excluded", 0),
            "status_counts": status_counts,
        }
    )
    ranking["summary"] = summary
    return ranking


def build_replan_hint_items(process_ids: set[int], state: dict[str, Any], ranking: dict[str, Any], evaluation: dict[str, Any]) -> list[dict[str, Any]]:
    ranking_items = ranking.get("items", []) or []
    evaluation_items = evaluation.get("items", []) or []
    items = []
    for process_id in sorted(process_ids):
        candidate = next((item for item in ranking_items if int(item.get("process_id") or 0) == process_id), {})
        eval_item = next((item for item in evaluation_items if int(item.get("process_id") or 0) == process_id), {})
        items.append(
            {
                "process_id": process_id,
                "candidate_agent_name": candidate.get("candidate_agent_name") or eval_item.get("candidate_agent_name"),
                "process_name": candidate.get("process_name"),
                "confidence_score": eval_item.get("confidence_score", 0),
                "evidence_coverage": eval_item.get("evidence_coverage", 0),
                "issues": eval_item.get("issues", []),
                "suggested_actions": [
                    "공식 URL 또는 내부 문서 추가 수집",
                    "업무 owner 인터뷰 메모 추가",
                    "RAG 재색인 후 재평가",
                ],
            }
        )
    return items


def apply_priority_post_decision(result: dict[str, Any], decision: dict[str, Any], state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    ranking = deepcopy(result.get("priority_ranking") or {})
    items = list(ranking.get("items", []) or [])
    adjusted_count = 0

    for item in items:
        if item.get("status") in {"excluded", "human_review_required", "evidence_insufficient"}:
            item["agent_decision_status"] = item.get("status")
            item["agent_decision_reason"] = "Business Case Agent preserved conservative governance/review status during ranking."
            adjusted_count += 1

    if items:
        ranking["items"] = items
        ranking = rebuild_priority_summary(ranking)
        if adjusted_count:
            ranking.setdefault("summary", {})["agent_decision_adjusted_count"] = adjusted_count
            ranking["summary"]["agent_decision_applied"] = True
        result["priority_ranking"] = ranking

    post_decision = {
        "phase": "post_tool_observation",
        "node_name": decision.get("node_name"),
        "agent_id": decision.get("agent_id"),
        "selected_tool": decision.get("selected_tool"),
        "decision": "preserve_review_status" if adjusted_count else "refresh_status_summary",
        "changed_output": bool(adjusted_count),
        "adjusted_count": adjusted_count,
        "reason": "Ranking results were checked against governance and human-review status, then summary counts were refreshed.",
    }
    return result, post_decision


def apply_evaluation_post_decision(result: dict[str, Any], decision: dict[str, Any], state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    evaluation = deepcopy(result.get("agent_evaluation") or state.get("agent_evaluation") or {})
    ranking = deepcopy(result.get("priority_ranking") or state.get("priority_ranking") or {})
    summary = evaluation.setdefault("summary", {})
    insufficient_ids, review_ids = split_evidence_decision_ids(evaluation)
    llm_review_count = count_llm_review_needs(evaluation)
    effective_required_count = max(int(summary.get("additional_evidence_required_count", 0) or 0), len(insufficient_ids | review_ids), llm_review_count)

    changed = False
    adjusted_count = 0
    if effective_required_count > 0:
        for item in ranking.get("items", []) or []:
            process_id = int(item.get("process_id") or 0)
            previous_status = item.get("status")
            if process_id in insufficient_ids:
                item.setdefault("status_before_agent_decision", previous_status)
                item["status"] = "evidence_insufficient"
                item["agent_decision_status"] = "replan_or_human_review_required"
                item["agent_decision_reason"] = "Evaluation & Critic Agent found a severe evidence gap for this candidate."
                adjusted_count += 1
            elif process_id in review_ids:
                item.setdefault("status_before_agent_decision", previous_status)
                item["status"] = "human_review_required"
                item["agent_decision_status"] = "human_review_required"
                item["agent_decision_reason"] = "Evaluation & Critic Agent requires human review, but did not classify the evidence gap as severe."
                adjusted_count += 1

        ranking = rebuild_priority_summary(ranking)
        summary["additional_evidence_required_count"] = len(insufficient_ids | review_ids)
        summary["evidence_insufficient_count"] = len(insufficient_ids)
        summary["human_review_required_count"] = ranking.get("summary", {}).get("human_review_required_count", 0)
        summary["agent_decision_adjusted_count"] = adjusted_count
        summary["agent_decision_applied"] = bool(adjusted_count)
        evaluation["summary"] = summary
        evaluation["agent_decision"] = {
            "decision": "request_replan_or_human_review" if adjusted_count else "pass_through",
            "reason": "Severe evidence gaps are routed to evidence_insufficient; weaker evidence or critic concerns are routed to human_review_required.",
            "insufficient_process_ids": sorted(insufficient_ids),
            "review_process_ids": sorted(review_ids),
            "fallback_route": "human_review",
        }
        result["agent_evaluation"] = evaluation
        result["priority_ranking"] = ranking
        if insufficient_ids and not result.get("replan_request"):
            result["replan_request"] = {
                "mode": "agent_decision_hint",
                "reason": "Evaluation & Critic Agent requested replan for candidates with severe evidence gaps.",
                "items": build_replan_hint_items(insufficient_ids, state, ranking, evaluation),
                "route_after_replan": "human_review",
            }
        changed = bool(adjusted_count)

    post_decision = {
        "phase": "post_tool_observation",
        "node_name": decision.get("node_name"),
        "agent_id": decision.get("agent_id"),
        "selected_tool": decision.get("selected_tool"),
        "decision": "request_replan_or_human_review" if changed else "pass_through",
        "changed_output": changed,
        "adjusted_count": adjusted_count,
        "evidence_insufficient_count": len(insufficient_ids),
        "review_required_count": len(review_ids),
        "additional_evidence_required_count": len(insufficient_ids | review_ids),
        "reason": "The critic distinguishes severe evidence insufficiency from ordinary human-review cases without changing unflagged recommended candidates.",
    }
    return result, post_decision


def apply_delivery_post_decision(result: dict[str, Any], decision: dict[str, Any], state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    changed = False
    adjusted_count = 0
    node_name = str(decision.get("node_name"))

    if node_name == "poc_delivery_planner" and result.get("poc_plan"):
        poc_plan = deepcopy(result.get("poc_plan") or {})
        ranking_items = ((result.get("priority_ranking") or state.get("priority_ranking") or {}).get("items") or [])
        held_items = [item for item in ranking_items if item.get("status") in {"evidence_insufficient", "excluded"}]
        review_items = [item for item in ranking_items if item.get("status") == "human_review_required"]
        first_candidate = poc_plan.get("first_individual_poc_candidate") or {}
        first_status = first_candidate.get("status") if isinstance(first_candidate, dict) else None

        if held_items or review_items or first_status in {"evidence_insufficient", "excluded", "human_review_required"}:
            selection_status = "provisional_review_required"
            if first_status in {"evidence_insufficient", "excluded"} or held_items:
                selection_status = "held_pending_evidence_or_governance"

            poc_plan.setdefault("mvp_agent", {})["selection_status"] = selection_status
            poc_plan.setdefault("mvp_agent", {})["selection_note"] = "PoC 후보는 자동 확정이 아니라 Human Review 이후 확정되는 provisional candidate이다."
            poc_plan["mvp_selection"] = {
                "status": selection_status,
                "held_candidate_count": len(held_items),
                "review_required_count": len(review_items),
                "reason": "Evaluation/Governance Agent decision requires follow-up before final PoC commitment.",
            }
            poc_plan["requires_governance_followup"] = bool(held_items)
            poc_plan["requires_human_review_followup"] = bool(review_items or held_items)
            poc_plan["agent_decision"] = {
                "decision": "guarded_poc_plan",
                "reason": "Candidate is treated as provisional until evidence/governance/human-review follow-up is completed.",
                "held_candidate_count": len(held_items),
                "review_required_count": len(review_items),
            }
            result["poc_plan"] = poc_plan
            changed = True
            adjusted_count = len(held_items) + len(review_items)

    if node_name == "report_writer" and result.get("report_data"):
        report_data = deepcopy(result.get("report_data") or {})
        decisions = [*(state.get("agent_decisions", []) or []), *(result.get("agent_decisions", []) or [])]
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


def apply_post_decision(result: dict[str, Any], decision: dict[str, Any], state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    node_name = str(decision.get("node_name"))
    mutable_result = deepcopy(result)

    if node_name == "priority_ranking":
        return apply_priority_post_decision(mutable_result, decision, state)
    if node_name in {"agent_evaluator", "llm_critic"}:
        return apply_evaluation_post_decision(mutable_result, decision, state)
    if node_name in {"poc_delivery_planner", "report_writer"}:
        return apply_delivery_post_decision(mutable_result, decision, state)

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
            "assigned_tools": pre_decision.get("assigned_tools", []),
            "planner_mode": pre_decision.get("planner_mode"),
            "planner_used_llm": pre_decision.get("planner_used_llm"),
            "selected_tool_uses_llm": pre_decision.get("selected_tool_uses_llm"),
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
            "assigned_tools": pre_decision.get("assigned_tools", []),
            "tool_name": pre_decision.get("selected_tool"),
            "tool_description": pre_decision.get("tool_description"),
            "tool_uses_llm": pre_decision.get("selected_tool_uses_llm"),
            "planner_mode": pre_decision.get("planner_mode"),
            "planner_used_llm": pre_decision.get("planner_used_llm"),
            "selection_reason": pre_decision.get("selection_reason"),
            "observation": tool_observation,
        }
    ]
    merged["agent_decisions"] = list(merged.get("agent_decisions", [])) + [pre_decision, post_decision]
    return merged


def expert_executed_node(node_name: str, node_fn: Callable[[StateT], dict[str, Any]]) -> Callable[[StateT], dict[str, Any]]:
    """Run a graph node through the assigned expert Agent.

    Flow:
    1. Resolve the expert Agent and its assigned tool specs from registry.py.
    2. Ask the Agent LLM planner to choose exactly one assigned tool.
    3. Validate and execute that tool through call_agent_tool permission checks.
    4. Ask the Agent post-tool reflector for next-action intent.
    5. Apply deterministic safety calibration and record all decisions.
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

        candidate_tool_specs = get_tool_specs_for_node(agent_id, node_name)
        if not candidate_tool_specs:
            raise ValueError(f"No tool_specs entry for agent '{agent_id}' and node '{node_name}'")
        if len(candidate_tool_specs) > 3:
            raise ValueError(f"Too many candidate tools for node '{node_name}': {len(candidate_tool_specs)}")

        fallback_tool_spec, fallback_reason = select_tool_spec(
            node_name=node_name,
            agent_spec=agent_spec,
            contract=contract,
            candidate_tool_specs=candidate_tool_specs,
            state=state,
        )
        state_summary = summarize_state_for_agent(state)
        planner_result = plan_agent_tool_selection(
            agent_spec=agent_spec,
            contract=contract,
            candidate_tool_specs=candidate_tool_specs,
            fallback_tool_spec=fallback_tool_spec,
            fallback_reason=fallback_reason,
            state_summary=state_summary,
        )
        selected_tool_spec = planner_result["selected_tool_spec"]

        pre_decision = build_agent_tool_decision(
            node_name=node_name,
            agent_spec=agent_spec,
            contract=contract,
            candidate_tool_specs=candidate_tool_specs,
            selected_tool_spec=selected_tool_spec,
            selection_reason=str(planner_result.get("reason") or fallback_reason),
            state=state,
            planner_result=planner_result,
        )

        tool_call = call_agent_tool(
            agent_id=agent_id,
            tool_name=str(selected_tool_spec["name"]),
            payload={"state": state, "agent_decision": pre_decision},
            runner=lambda payload: node_fn(payload["state"]),
            node_name=node_name,
        )

        llm_post_decision = plan_agent_post_decision(
            agent_spec=agent_spec,
            contract=contract,
            selected_tool_spec=selected_tool_spec,
            tool_observation=tool_call.observation,
            state_summary=state_summary,
        )
        post_processed_result, post_decision = apply_post_decision(tool_call.result, pre_decision, state)
        post_decision = {
            **post_decision,
            "agent_post_planner": llm_post_decision,
            "post_planner_mode": llm_post_decision.get("planner_mode"),
            "post_planner_used_llm": llm_post_decision.get("planner_used_llm"),
        }

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
