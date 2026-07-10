# app/agents/supervisor_llm.py

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.prompts import ChatPromptTemplate

from app.agents.model_router import SUPERVISOR_AGENT_ID, compact_model_assignment
from app.agents.registry import get_tool_specs_for_node
from app.core.config import get_settings
from app.core.llm import get_chat_model, invoke_chat_with_retry


SYSTEM_PROMPT = """
You are the AX Delivery Supervisor Agent.
You are an autonomous AI Agent, not a passive router.
Your job is to control the whole multi-agent workflow: delegate work to Expert Agents,
choose what tools they should emphasize, keep the work evidence-grounded, minimize
unnecessary human approvals, and escalate only when human approval is genuinely needed.

Rules:
- You do not execute tools directly. You delegate to Expert Agents and define their tool policy.
- Use only the listed stage nodes and listed tool specs.
- Prefer autonomous execution for evidence loading, RAG search, scoring, critique, report drafting, and DOCX export.
- Require human approval only for final business commitment, sensitive/high-impact/prohibited-use risk,
  severe evidence insufficiency, or a user-provided manual override.
- Return JSON only.
""".strip()


DELEGATION_PROMPT = """
Workflow goal:
{workflow_goal}

Current stage:
{stage_context}

Expert Agent contract:
{agent_contract}

Assigned internal nodes and tools:
{assigned_work}

Incoming handoff context:
{handoff_context}

State summary:
{state_summary}

Current model assignment:
{model_assignment}

Return JSON only:
{{
  "supervisor_intent": "Korean sentence describing what you want this stage to accomplish",
  "delegated_to": "agent id",
  "stage_name": "stage name",
  "autonomy_level": "high|bounded|approval_required",
  "node_order": ["assigned node name"],
  "tool_policy": [
    {{
      "node_name": "assigned node name",
      "tool_priorities": ["assigned tool name"],
      "autonomy": "auto_execute|auto_validate|ask_human_before_action",
      "instruction": "Korean instruction for the Expert Agent",
      "approval_required": false,
      "approval_reason": ""
    }}
  ],
  "human_approval_policy": {{
    "requires_human_approval": false,
    "approval_gates": ["risk_sensitive|evidence_insufficient|final_commitment"],
    "minimal_approval_reason": "Korean reason why approval is or is not needed now"
  }},
  "allowed_auto_actions": ["load_db_context", "retrieve_rag", "run_scoring", "run_critic", "draft_report", "export_docx"],
  "stop_conditions": ["Korean stop/escalation condition"],
  "route_hint": "continue|replan|human_review|stop",
  "risk_note": "Korean risk/control note"
}}
""".strip()


def compact_json(value: Any, max_chars: int = 6000) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        text = str(value)
    return text if len(text) <= max_chars else text[:max_chars] + "..."


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()

    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise
        payload = json.loads(match.group(0))

    if not isinstance(payload, dict):
        raise ValueError("Supervisor LLM response JSON must be an object")
    return payload


def safe_settings_timeout(default: float = 10.0) -> float:
    try:
        settings = get_settings()
        return float(getattr(settings, "agent_llm_timeout_seconds", default) or default)
    except Exception:
        return default


def assigned_work_for_nodes(agent_id: str, internal_nodes: list[str]) -> list[dict[str, Any]]:
    """Supervisor가 볼 수 있는 stage별 tool catalog를 만든다."""

    work: list[dict[str, Any]] = []
    for node_name in internal_nodes:
        tools = get_tool_specs_for_node(agent_id, node_name)
        work.append(
            {
                "node_name": node_name,
                "assigned_tools": [
                    {
                        "name": tool.get("name"),
                        "purpose": tool.get("purpose", "execute"),
                        "description": tool.get("description"),
                    }
                    for tool in tools
                ],
            }
        )
    return work


def summarize_state_for_supervisor(state: dict[str, Any]) -> dict[str, Any]:
    """Supervisor가 판단에 필요한 state 신호만 압축한다."""

    priority_items = (state.get("priority_ranking") or {}).get("items", []) or []
    statuses: dict[str, int] = {}
    for item in priority_items:
        status = str(item.get("status") or "unknown")
        statuses[status] = statuses.get(status, 0) + 1

    evaluation_summary = (state.get("agent_evaluation") or {}).get("summary", {}) or {}
    compliance_summary = (state.get("compliance_assessment") or {}).get("summary", {}) or {}

    return {
        "project_id": state.get("project_id"),
        "company_id": state.get("company_id"),
        "user_request": state.get("user_request"),
        "business_process_count": len(state.get("business_processes", []) or []),
        "document_count": len(state.get("documents", []) or []),
        "evidence_item_count": len(state.get("evidence_items", []) or []),
        "used_source_count": len(state.get("used_sources", []) or []),
        "priority_candidate_count": len(priority_items),
        "priority_status_counts": statuses,
        "evaluation_summary": evaluation_summary,
        "compliance_summary": compliance_summary,
        "has_replan_request": bool(state.get("replan_request")),
        "has_human_review": bool(state.get("human_review")),
        "has_report_data": bool(state.get("report_data")),
        "errors": state.get("errors", [])[-5:],
    }


def sanitize_node_order(raw_order: Any, internal_nodes: list[str]) -> list[str]:
    if not isinstance(raw_order, list):
        return internal_nodes
    ordered = [str(item) for item in raw_order if str(item) in internal_nodes]
    ordered += [node for node in internal_nodes if node not in ordered]
    return ordered or internal_nodes


def build_default_tool_policy(agent_id: str, internal_nodes: list[str]) -> list[dict[str, Any]]:
    """LLM 실패 시에도 하위 Agent가 자율 실행할 수 있게 기본 도구정책을 만든다."""

    policies: list[dict[str, Any]] = []
    for node_name in internal_nodes:
        tools = get_tool_specs_for_node(agent_id, node_name)
        policies.append(
            {
                "node_name": node_name,
                "tool_priorities": [str(tool.get("name")) for tool in tools if tool.get("name")],
                "autonomy": "auto_execute",
                "instruction": f"{node_name}를 자동 실행하고 결과와 근거를 다음 Agent에 넘긴다.",
                "approval_required": False,
                "approval_reason": "",
            }
        )
    return policies


def fallback_supervisor_delegation(
    *,
    agent_id: str,
    stage_name: str,
    internal_nodes: list[str],
    reason: str,
    model_assignment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Supervisor LLM이 실패해도 자율 workflow가 멈추지 않게 하는 위임장."""

    return {
        "agent_id": SUPERVISOR_AGENT_ID,
        "llm_used": False,
        "mode": "deterministic_fallback_supervisor_delegation",
        "supervisor_intent": f"{agent_id}에게 {stage_name} stage를 기본 자율 정책으로 위임한다.",
        "delegated_to": agent_id,
        "stage_name": stage_name,
        "autonomy_level": "bounded",
        "node_order": internal_nodes,
        "tool_policy": build_default_tool_policy(agent_id, internal_nodes),
        "human_approval_policy": {
            "requires_human_approval": False,
            "approval_gates": ["risk_sensitive", "evidence_insufficient", "final_commitment"],
            "minimal_approval_reason": "Supervisor LLM fallback 상태이므로 일반 분석은 자동 진행하고, 위험/근거부족/최종 확정만 사람 승인으로 올린다.",
        },
        "allowed_auto_actions": [
            "load_db_context",
            "retrieve_rag",
            "run_scoring",
            "run_critic",
            "draft_report",
            "export_docx",
        ],
        "stop_conditions": ["금지 가능 사용, 고영향/민감정보 리스크, 심각한 근거 부족이 확인되면 Human Review로 전환한다."],
        "route_hint": "continue",
        "risk_note": reason,
        "reason": reason,
        "model_selection": compact_model_assignment(model_assignment),
    }


def normalize_human_approval_policy(payload: dict[str, Any]) -> dict[str, Any]:
    policy = payload.get("human_approval_policy")
    if not isinstance(policy, dict):
        policy = {}
    gates = policy.get("approval_gates")
    if not isinstance(gates, list):
        gates = ["risk_sensitive", "evidence_insufficient", "final_commitment"]
    return {
        "requires_human_approval": bool(policy.get("requires_human_approval", False)),
        "approval_gates": [str(item) for item in gates],
        "minimal_approval_reason": str(policy.get("minimal_approval_reason") or "일반 자동 실행 단계로 판단했다."),
    }


def normalize_supervisor_delegation(
    *,
    payload: dict[str, Any],
    agent_id: str,
    stage_name: str,
    internal_nodes: list[str],
    model_assignment: dict[str, Any] | None,
) -> dict[str, Any]:
    """LLM 응답을 런타임이 믿고 쓸 수 있는 형태로 정규화한다."""

    tool_policy = payload.get("tool_policy")
    if not isinstance(tool_policy, list):
        tool_policy = build_default_tool_policy(agent_id, internal_nodes)

    normalized_policy = []
    internal_node_set = set(internal_nodes)
    for item in tool_policy:
        if not isinstance(item, dict):
            continue
        node_name = str(item.get("node_name") or "")
        if node_name not in internal_node_set:
            continue
        priorities = item.get("tool_priorities")
        normalized_policy.append(
            {
                "node_name": node_name,
                "tool_priorities": [str(tool) for tool in priorities] if isinstance(priorities, list) else [],
                "autonomy": str(item.get("autonomy") or "auto_execute"),
                "instruction": str(item.get("instruction") or f"{node_name}를 실행한다."),
                "approval_required": bool(item.get("approval_required", False)),
                "approval_reason": str(item.get("approval_reason") or ""),
            }
        )

    if not normalized_policy:
        normalized_policy = build_default_tool_policy(agent_id, internal_nodes)

    route_hint = str(payload.get("route_hint") or "continue")
    if route_hint not in {"continue", "replan", "human_review", "stop"}:
        route_hint = "continue"

    return {
        "agent_id": SUPERVISOR_AGENT_ID,
        "llm_used": True,
        "mode": "supervisor_llm_delegation",
        "supervisor_intent": str(payload.get("supervisor_intent") or f"{agent_id}에게 {stage_name} stage를 위임한다."),
        "delegated_to": agent_id,
        "stage_name": stage_name,
        "autonomy_level": str(payload.get("autonomy_level") or "bounded"),
        "node_order": sanitize_node_order(payload.get("node_order"), internal_nodes),
        "tool_policy": normalized_policy,
        "human_approval_policy": normalize_human_approval_policy(payload),
        "allowed_auto_actions": payload.get("allowed_auto_actions") if isinstance(payload.get("allowed_auto_actions"), list) else [],
        "stop_conditions": payload.get("stop_conditions") if isinstance(payload.get("stop_conditions"), list) else [],
        "route_hint": route_hint,
        "risk_note": str(payload.get("risk_note") or ""),
        "model_selection": compact_model_assignment(model_assignment),
    }


def run_supervisor_delegation_prompt(
    *,
    agent_spec: dict[str, Any],
    stage_name: str,
    internal_nodes: list[str],
    state: dict[str, Any],
    incoming_handoffs: list[dict[str, Any]] | None = None,
    loop_index: int = 1,
    model_assignment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """상위 Supervisor LLM을 실제로 호출해 Expert Agent 위임장을 만든다."""

    agent_id = str(agent_spec.get("id") or stage_name)
    try:
        settings = get_settings()
        if not settings.supervisor_llm_enabled:
            return fallback_supervisor_delegation(
                agent_id=agent_id,
                stage_name=stage_name,
                internal_nodes=internal_nodes,
                reason="SUPERVISOR_LLM_ENABLED=false 이므로 deterministic Supervisor 위임장을 사용한다.",
                model_assignment=model_assignment,
            )

        llm = get_chat_model(temperature=0.0, timeout=safe_settings_timeout(), model_assignment=model_assignment)
        prompt = ChatPromptTemplate.from_messages([("system", SYSTEM_PROMPT), ("human", DELEGATION_PROMPT)])
        messages = prompt.format_messages(
            workflow_goal=compact_json(
                {
                    "supervisor_agent_id": SUPERVISOR_AGENT_ID,
                    "objective": state.get("user_request"),
                    "policy": "autonomous multi-agent delivery planning with minimal human approval",
                    "loop_index": loop_index,
                },
                max_chars=1200,
            ),
            stage_context=compact_json(
                {
                    "stage_name": stage_name,
                    "delegated_to": agent_id,
                    "internal_nodes": internal_nodes,
                    "loop_index": loop_index,
                },
                max_chars=1200,
            ),
            agent_contract=compact_json(
                {
                    "id": agent_spec.get("id"),
                    "name": agent_spec.get("name"),
                    "purpose": agent_spec.get("purpose"),
                    "role_prompt": agent_spec.get("role_prompt"),
                    "task_instructions": agent_spec.get("task_instructions", []),
                    "quality_checks": agent_spec.get("quality_checks", []),
                    "output_contract": agent_spec.get("output_contract", []),
                    "controls": agent_spec.get("controls", []),
                    "human_review_required": agent_spec.get("human_review_required", False),
                },
                max_chars=5200,
            ),
            assigned_work=compact_json(assigned_work_for_nodes(agent_id, internal_nodes), max_chars=5200),
            handoff_context=compact_json(incoming_handoffs or [], max_chars=3000),
            state_summary=compact_json(summarize_state_for_supervisor(state), max_chars=3600),
            model_assignment=compact_json(compact_model_assignment(model_assignment), max_chars=1200),
        )
        response = invoke_chat_with_retry(llm, messages, retries=0)
        payload = extract_json_object(str(response.content))
        return normalize_supervisor_delegation(
            payload=payload,
            agent_id=agent_id,
            stage_name=stage_name,
            internal_nodes=internal_nodes,
            model_assignment=model_assignment,
        )
    except Exception as exc:
        return fallback_supervisor_delegation(
            agent_id=agent_id,
            stage_name=stage_name,
            internal_nodes=internal_nodes,
            reason=f"Supervisor LLM delegation failed: {type(exc).__name__}: {exc}",
            model_assignment=model_assignment,
        )


def build_supervisor_llm_call_record(payload: dict[str, Any]) -> dict[str, Any]:
    """agent_llm_calls와 같은 trace 형식으로 Supervisor 호출을 기록한다."""

    return {
        "kind": "supervisor_delegation",
        "agent_id": payload.get("agent_id", SUPERVISOR_AGENT_ID),
        "stage_name": payload.get("stage_name"),
        "loop_index": payload.get("loop_index", 1),
        "llm_used": bool(payload.get("llm_used")),
        "mode": payload.get("mode"),
        "decision": payload.get("route_hint"),
        "node_order": payload.get("node_order"),
        "needs_iteration": False,
        "reason": payload.get("supervisor_intent") or payload.get("reason"),
        "handoff_plan": {
            "delegated_to": payload.get("delegated_to"),
            "autonomy_level": payload.get("autonomy_level"),
            "human_approval_policy": payload.get("human_approval_policy", {}),
        },
        "risk_note": payload.get("risk_note"),
        "model_selection": payload.get("model_selection", {}),
    }

