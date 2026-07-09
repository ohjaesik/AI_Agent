# app/agents/expert_executor.py

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any, TypeVar

from app.agents.registry import get_agent_spec, get_tool_specs_for_node
from app.agents.runtime import build_agent_contract, build_contract_audit_log, get_agent_binding_for_node
from app.agents.tool_runtime import call_agent_tool
from app.core.config import get_settings

StateT = TypeVar("StateT", bound=dict[str, Any])

EVIDENCE_INSUFFICIENT_THRESHOLD = 0.15
LOW_CONFIDENCE_THRESHOLD = 0.45
DEFAULT_AGENT_SUPERVISOR_MAX_LOOPS = 2
EXPLICIT_EXTRA_LOOP_BONUS = 1


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
        "agent_supervisor_extra_loop_enabled": bool(state.get("agent_supervisor_extra_loop_enabled")),
        "available_state_keys": sorted(state.keys()),
    }


def tool_names(tool_specs: list[dict[str, Any]]) -> list[str]:
    return [str(item.get("name")) for item in tool_specs if item.get("name")]


def tool_uses_llm(tool_spec: dict[str, Any]) -> bool:
    name = str(tool_spec.get("name") or "")
    return bool(tool_spec.get("uses_llm")) or "llm" in name.lower() or name in {"process_discovery_llm", "llm_critic", "report_writer"}


def summarize_assigned_tool(tool_spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": tool_spec.get("name"),
        "description": tool_spec.get("description"),
        "purpose": tool_spec.get("purpose", "execute"),
        "nodes": tool_spec.get("nodes", []),
        "uses_llm": tool_uses_llm(tool_spec),
    }


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def get_agent_loop_settings(state: dict[str, Any]) -> tuple[int, bool, str | None]:
    """Resolve loop policy without breaking tests when env settings are absent."""
    try:
        settings = get_settings()
        max_loops = int(settings.agent_supervisor_max_tool_loops or DEFAULT_AGENT_SUPERVISOR_MAX_LOOPS)
        extra_loop_enabled = bool(settings.agent_supervisor_extra_loop_enabled)
        settings_error = None
    except Exception as exc:
        max_loops = DEFAULT_AGENT_SUPERVISOR_MAX_LOOPS
        extra_loop_enabled = False
        settings_error = f"settings_unavailable: {type(exc).__name__}: {exc}"

    if state.get("agent_supervisor_extra_loop_enabled"):
        extra_loop_enabled = True

    max_loops = max(1, min(max_loops, DEFAULT_AGENT_SUPERVISOR_MAX_LOOPS))
    if extra_loop_enabled:
        max_loops += EXPLICIT_EXTRA_LOOP_BONUS

    return max_loops, extra_loop_enabled, settings_error


def order_assigned_tools(candidate_tool_specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep registry order but make sure execute tools are first when present."""
    execute_tools = [tool for tool in candidate_tool_specs if str(tool.get("purpose") or "execute") == "execute"]
    other_tools = [tool for tool in candidate_tool_specs if tool not in execute_tools]
    return [*execute_tools, *other_tools]


def select_tool_spec(
    *,
    node_name: str,
    agent_spec: dict[str, Any],
    contract: dict[str, Any],
    candidate_tool_specs: list[dict[str, Any]],
    state: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    """Select the emphasized tool for trace readability.

    The Supervisor loop still runs the assigned tool set. This selector only identifies
    which assigned tool carries the Agent's main decision emphasis.
    """
    if not candidate_tool_specs:
        raise ValueError(f"No candidate tool specs for node: {node_name}")

    ordered_tools = order_assigned_tools(candidate_tool_specs)
    by_name = {str(item.get("name")): item for item in ordered_tools}
    evaluation_summary = (state.get("agent_evaluation") or {}).get("summary", {}) or {}
    additional_evidence_count = int(evaluation_summary.get("additional_evidence_required_count", 0) or 0)
    priority_items = (state.get("priority_ranking") or {}).get("items", []) or []
    review_count = sum(1 for item in priority_items if item.get("status") == "human_review_required")
    blocked_count = sum(1 for item in priority_items if item.get("status") == "excluded")

    selection_rules = [
        (
            node_name == "priority_ranking" and (review_count > 0 or blocked_count > 0) and "candidate_status_calibrator" in by_name,
            "candidate_status_calibrator",
            "governance or review-required candidates exist, so this assigned calibration tool is emphasized inside the Agent loop.",
        ),
        (
            node_name == "agent_evaluator" and "evidence_replan_decider" in by_name,
            "evidence_replan_decider",
            "evaluation must decide whether weak evidence should trigger bounded replan or human review.",
        ),
        (
            node_name == "llm_critic" and additional_evidence_count > 0 and "critic_replan_decider" in by_name,
            "critic_replan_decider",
            "previous evaluation found evidence gaps, so this assigned routing tool is emphasized inside the Agent loop.",
        ),
        (
            node_name == "poc_delivery_planner" and review_count == len(priority_items) and priority_items and "poc_candidate_guard" in by_name,
            "poc_candidate_guard",
            "all candidates require review, so this assigned guard tool is emphasized inside the Agent loop.",
        ),
        (
            node_name == "report_writer" and state.get("agent_decisions") and "delivery_decision_summarizer" in by_name,
            "delivery_decision_summarizer",
            "previous Agent decisions exist and must be reflected in the final report metadata.",
        ),
    ]

    for condition, selected_name, reason in selection_rules:
        if condition:
            return by_name[selected_name], reason

    default_tool = ordered_tools[0]
    return default_tool, (
        f"{agent_spec.get('name')} emphasized the primary assigned tool for capability '{contract.get('capability')}'."
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
    loop_index: int,
    tool_index: int,
    loop_limit: int,
    executes_node: bool,
) -> dict[str, Any]:
    return {
        "phase": "agent_tool_loop",
        "node_name": node_name,
        "agent_id": agent_spec.get("id"),
        "agent_name": agent_spec.get("name"),
        "capability": contract.get("capability"),
        "node_role": contract.get("node_role"),
        "loop_index": loop_index,
        "loop_limit": loop_limit,
        "tool_index": tool_index,
        "candidate_tools": tool_names(candidate_tool_specs),
        "assigned_tools": [summarize_assigned_tool(tool) for tool in candidate_tool_specs],
        "selected_tool": selected_tool_spec.get("name"),
        "selected_tool_purpose": selected_tool_spec.get("purpose", "execute"),
        "selected_tool_uses_llm": tool_uses_llm(selected_tool_spec),
        "executes_node": executes_node,
        "tool_description": selected_tool_spec.get("description"),
        "selection_reason": selection_reason,
        "planner_mode": "expert_agent_supervisor_loop",
        "planner_used_llm": False,
        "role_prompt": agent_spec.get("role_prompt", ""),
        "task_instructions": agent_spec.get("task_instructions", []),
        "state_summary": summarize_state_for_agent(state),
    }


def split_evidence_decision_ids(agent_evaluation: dict[str, Any]) -> tuple[set[int], set[int]]:
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


def agent_loop_condition(node_name: str, post_decision: dict[str, Any], result: dict[str, Any]) -> bool:
    if node_name in {"agent_evaluator", "llm_critic"}:
        if int(post_decision.get("additional_evidence_required_count") or 0) > 0 and not result.get("replan_request"):
            return True

    if node_name == "poc_delivery_planner" and post_decision.get("changed_output"):
        return True

    return False


def agent_needs_next_loop(node_name: str, post_decision: dict[str, Any], result: dict[str, Any], loop_index: int, loop_limit: int) -> bool:
    return loop_index < loop_limit and agent_loop_condition(node_name, post_decision, result)


def build_extra_loop_request(
    *,
    node_name: str,
    agent_id: str,
    post_decision: dict[str, Any],
    state: dict[str, Any],
    loop_limit: int,
) -> dict[str, Any]:
    project_id = state.get("project_id")
    command = "python -m app.main --auto-approve --allow-agent-extra-loop"
    if project_id:
        command += f" --project-id {project_id}"
    return {
        "node_name": node_name,
        "agent_id": agent_id,
        "reason": post_decision.get("reason"),
        "loop_limit_reached": loop_limit,
        "requested_extra_loops": 1,
        "command": command,
        "default_action": "skip_extra_loop_and_continue",
    }


def validation_runner_result(current_result: dict[str, Any], tool_spec: dict[str, Any], loop_index: int) -> dict[str, Any]:
    result = dict(current_result)
    validations = list(result.get("agent_tool_validations", []))
    validations.append(
        {
            "tool_name": tool_spec.get("name"),
            "purpose": tool_spec.get("purpose", "execute"),
            "loop_index": loop_index,
            "status": "observed_existing_node_result",
        }
    )
    result["agent_tool_validations"] = validations
    return result


def run_agent_tool_loop(
    *,
    node_name: str,
    node_fn: Callable[[StateT], dict[str, Any]],
    state: StateT,
    agent_spec: dict[str, Any],
    contract: dict[str, Any],
    candidate_tool_specs: list[dict[str, Any]],
    emphasized_tool_spec: dict[str, Any],
    emphasized_reason: str,
) -> dict[str, Any]:
    agent_id = str(agent_spec.get("id"))
    loop_limit, extra_loop_enabled, settings_note = get_agent_loop_settings(state)
    assigned_tools = order_assigned_tools(candidate_tool_specs)
    current_result: dict[str, Any] = {}
    all_audit_logs: list[dict[str, Any]] = []
    pre_decisions: list[dict[str, Any]] = []
    post_decisions: list[dict[str, Any]] = []
    tool_call_records: list[dict[str, Any]] = []
    loop_iterations: list[dict[str, Any]] = []

    for loop_index in range(1, loop_limit + 1):
        loop_state = {**state, **current_result}
        loop_tool_names: list[str] = []
        loop_observations: list[dict[str, Any]] = []

        for tool_index, tool_spec in enumerate(assigned_tools, start=1):
            executes_node = tool_index == 1
            reason = emphasized_reason if tool_spec.get("name") == emphasized_tool_spec.get("name") else (
                f"{agent_spec.get('name')} runs assigned tool '{tool_spec.get('name')}' in supervisor loop {loop_index}."
            )
            pre_decision = build_agent_tool_decision(
                node_name=node_name,
                agent_spec=agent_spec,
                contract=contract,
                candidate_tool_specs=assigned_tools,
                selected_tool_spec=tool_spec,
                selection_reason=reason,
                state=loop_state,
                loop_index=loop_index,
                tool_index=tool_index,
                loop_limit=loop_limit,
                executes_node=executes_node,
            )

            if executes_node:
                runner = lambda payload: node_fn(payload["state"])
            else:
                runner = lambda payload, tool_spec=tool_spec, loop_index=loop_index: validation_runner_result(current_result, tool_spec, loop_index)

            tool_call = call_agent_tool(
                agent_id=agent_id,
                tool_name=str(tool_spec["name"]),
                payload={"state": loop_state, "agent_decision": pre_decision},
                runner=runner,
                node_name=node_name,
            )

            current_result = dict(tool_call.result)
            pre_decisions.append(pre_decision)
            all_audit_logs.extend(tool_call.audit_logs)
            loop_tool_names.append(str(tool_spec.get("name")))
            loop_observations.append(tool_call.observation)
            tool_call_records.append(
                {
                    "node_name": node_name,
                    "agent_id": agent_id,
                    "capability": pre_decision.get("capability"),
                    "loop_index": loop_index,
                    "tool_index": tool_index,
                    "candidate_tools": pre_decision.get("candidate_tools", []),
                    "assigned_tools": pre_decision.get("assigned_tools", []),
                    "tool_name": pre_decision.get("selected_tool"),
                    "tool_description": pre_decision.get("tool_description"),
                    "tool_purpose": pre_decision.get("selected_tool_purpose"),
                    "tool_uses_llm": pre_decision.get("selected_tool_uses_llm"),
                    "executes_node": executes_node,
                    "planner_mode": "expert_agent_supervisor_loop",
                    "planner_used_llm": False,
                    "selection_reason": pre_decision.get("selection_reason"),
                    "observation": tool_call.observation,
                }
            )

        post_processed_result, post_decision = apply_post_decision(current_result, pre_decisions[-1], {**state, **current_result})
        current_result = post_processed_result
        post_decision = {
            **post_decision,
            "loop_index": loop_index,
            "loop_limit": loop_limit,
            "assigned_tools_executed": loop_tool_names,
            "agent_loop_mode": "expert_agent_supervisor_loop",
            "extra_loop_enabled": extra_loop_enabled,
            "settings_note": settings_note,
        }
        post_decisions.append(post_decision)
        loop_iterations.append(
            {
                "node_name": node_name,
                "agent_id": agent_id,
                "loop_index": loop_index,
                "loop_limit": loop_limit,
                "assigned_tools_executed": loop_tool_names,
                "observation_count": len(loop_observations),
                "post_decision": post_decision,
            }
        )

        if not agent_needs_next_loop(node_name, post_decision, current_result, loop_index, loop_limit):
            break

    last_post_decision = post_decisions[-1] if post_decisions else {}
    loop_requests = list(current_result.get("agent_loop_requests", []))
    if (
        not extra_loop_enabled
        and last_post_decision
        and len(loop_iterations) >= DEFAULT_AGENT_SUPERVISOR_MAX_LOOPS
        and agent_loop_condition(node_name, last_post_decision, current_result)
    ):
        loop_requests.append(
            build_extra_loop_request(
                node_name=node_name,
                agent_id=agent_id,
                post_decision=last_post_decision,
                state=state,
                loop_limit=DEFAULT_AGENT_SUPERVISOR_MAX_LOOPS,
            )
        )

    merged = dict(current_result)
    existing_audit_logs = list(merged.get("audit_logs", []))
    merged["audit_logs"] = [
        *all_audit_logs,
        *existing_audit_logs,
        build_contract_audit_log(node_name, {**contract, "selected_tool_spec": emphasized_tool_spec}),
    ]
    merged["agent_contracts"] = list(merged.get("agent_contracts", [])) + [
        {
            **contract,
            "selected_tool": emphasized_tool_spec.get("name"),
            "candidate_tools": tool_names(assigned_tools),
            "assigned_tools": [summarize_assigned_tool(tool) for tool in assigned_tools],
            "agent_loop_mode": "expert_agent_supervisor_loop",
            "loop_limit": loop_limit,
            "loop_iterations": loop_iterations,
            "post_decision": last_post_decision,
        }
    ]
    merged["agent_tool_calls"] = list(merged.get("agent_tool_calls", [])) + tool_call_records
    merged["agent_decisions"] = list(merged.get("agent_decisions", [])) + pre_decisions + post_decisions
    merged["agent_loop_iterations"] = list(merged.get("agent_loop_iterations", [])) + loop_iterations
    if loop_requests:
        merged["agent_loop_requests"] = loop_requests
    return merged


def expert_executed_node(node_name: str, node_fn: Callable[[StateT], dict[str, Any]]) -> Callable[[StateT], dict[str, Any]]:
    """Run a graph node through the top-level expert-agent supervisor loop.

    The top-level supervisor resolves the owning Expert Agent, gives it only the
    tools assigned in AgentSpec.tool_specs for the node, executes those assigned
    tools in order, and lets deterministic post-decision rules patch the state.
    The loop runs at most two times by default. A third loop requires explicit
    command/state opt-in via --allow-agent-extra-loop.
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

        emphasized_tool_spec, emphasized_reason = select_tool_spec(
            node_name=node_name,
            agent_spec=agent_spec,
            contract=contract,
            candidate_tool_specs=candidate_tool_specs,
            state=state,
        )

        return run_agent_tool_loop(
            node_name=node_name,
            node_fn=node_fn,
            state=state,
            agent_spec=agent_spec,
            contract=contract,
            candidate_tool_specs=candidate_tool_specs,
            emphasized_tool_spec=emphasized_tool_spec,
            emphasized_reason=emphasized_reason,
        )

    _node.__name__ = f"expert_supervised_{node_name}"
    return _node
