# app/agents/llm_planner.py

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.prompts import ChatPromptTemplate

from app.core.config import get_settings
from app.core.llm import get_chat_model, invoke_chat_with_retry

LLM_TOOL_NAMES = {"process_discovery_llm", "llm_critic", "report_writer"}

SYSTEM_PROMPT = """
You are the runtime planner for one expert Agent in a LangGraph AX delivery workflow.

You must choose exactly one tool from the assigned tool list.
The tool must be one of the provided tool names. Do not invent tools.
Use the Agent role, task instructions, node capability, state summary, and tool specs.
Return JSON only.
""".strip()

USER_PROMPT = """
Agent:
{agent}

Node contract:
{contract}

Assigned tools for this Agent/node:
{candidate_tools}

State summary:
{state_summary}

Fallback tool selected by deterministic policy:
{fallback_tool}

Return JSON:
{{
  "selected_tool": "one assigned tool name",
  "reason": "short Korean reason",
  "needs_llm": true,
  "risk_note": "short Korean note"
}}
""".strip()

POST_SYSTEM_PROMPT = """
You are the post-tool reflector for one expert Agent.
You observe the selected tool result and decide what the Agent should do next.
Return JSON only. Do not invent facts.
""".strip()

POST_USER_PROMPT = """
Agent:
{agent}

Node contract:
{contract}

Selected tool:
{selected_tool}

Tool observation:
{tool_observation}

State summary:
{state_summary}

Return JSON:
{{
  "decision": "pass|modify|replan|human_review",
  "changed_output_intent": true,
  "reason": "short Korean reason"
}}
""".strip()


def compact_json(value: Any, max_chars: int = 5000) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= max_chars else text[:max_chars] + "..."


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def tool_uses_llm(tool_spec: dict[str, Any]) -> bool:
    name = str(tool_spec.get("name") or "")
    return bool(tool_spec.get("uses_llm")) or name in LLM_TOOL_NAMES or "llm" in name.lower()


def summarize_tool_for_planner(tool_spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": tool_spec.get("name"),
        "description": tool_spec.get("description"),
        "purpose": tool_spec.get("purpose", "execute"),
        "nodes": tool_spec.get("nodes", []),
        "uses_llm": tool_uses_llm(tool_spec),
        "execution_backend": tool_spec.get("execution_backend", "node_tool"),
    }


def assigned_tool_names(candidate_tool_specs: list[dict[str, Any]]) -> set[str]:
    return {str(tool.get("name")) for tool in candidate_tool_specs if tool.get("name")}


def fallback_selection(
    *,
    fallback_tool_spec: dict[str, Any],
    candidate_tool_specs: list[dict[str, Any]],
    reason: str,
    mode: str,
) -> dict[str, Any]:
    return {
        "selected_tool_spec": dict(fallback_tool_spec),
        "planner_mode": mode,
        "planner_used_llm": False,
        "selected_tool_uses_llm": tool_uses_llm(fallback_tool_spec),
        "assigned_tools": [summarize_tool_for_planner(tool) for tool in candidate_tool_specs],
        "reason": reason,
        "risk_note": "LLM planner unavailable or disabled; deterministic fallback tool was used.",
    }


def plan_agent_tool_selection(
    *,
    agent_spec: dict[str, Any],
    contract: dict[str, Any],
    candidate_tool_specs: list[dict[str, Any]],
    fallback_tool_spec: dict[str, Any],
    fallback_reason: str,
    state_summary: dict[str, Any],
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.agent_llm_planner_enabled:
        return fallback_selection(
            fallback_tool_spec=fallback_tool_spec,
            candidate_tool_specs=candidate_tool_specs,
            reason=fallback_reason,
            mode="deterministic_planner_disabled",
        )

    candidates_by_name = {str(tool.get("name")): tool for tool in candidate_tool_specs if tool.get("name")}
    if len(candidates_by_name) <= 1:
        return fallback_selection(
            fallback_tool_spec=fallback_tool_spec,
            candidate_tool_specs=candidate_tool_specs,
            reason="Only one assigned tool is available for this Agent/node.",
            mode="single_assigned_tool",
        )

    try:
        prompt = ChatPromptTemplate.from_messages([("system", SYSTEM_PROMPT), ("human", USER_PROMPT)])
        llm = get_chat_model(temperature=0.0, timeout=settings.agent_llm_planner_timeout_seconds)
        messages = prompt.format_messages(
            agent=compact_json(
                {
                    "id": agent_spec.get("id"),
                    "name": agent_spec.get("name"),
                    "role_prompt": agent_spec.get("role_prompt"),
                    "task_instructions": agent_spec.get("task_instructions", []),
                    "quality_checks": agent_spec.get("quality_checks", []),
                    "output_contract": agent_spec.get("output_contract", []),
                },
                max_chars=4500,
            ),
            contract=compact_json(contract, max_chars=2500),
            candidate_tools=compact_json([summarize_tool_for_planner(tool) for tool in candidate_tool_specs], max_chars=4500),
            state_summary=compact_json(state_summary, max_chars=3500),
            fallback_tool=compact_json(summarize_tool_for_planner(fallback_tool_spec), max_chars=1200),
        )
        response = invoke_chat_with_retry(llm, messages, retries=0)
        payload = extract_json_object(str(response.content))
        selected_name = str(payload.get("selected_tool") or "")
        selected_tool_spec = candidates_by_name.get(selected_name)
        if not selected_tool_spec:
            return fallback_selection(
                fallback_tool_spec=fallback_tool_spec,
                candidate_tool_specs=candidate_tool_specs,
                reason=f"LLM selected an unassigned tool '{selected_name}', so deterministic fallback was used.",
                mode="llm_invalid_tool_fallback",
            )

        return {
            "selected_tool_spec": dict(selected_tool_spec),
            "planner_mode": "llm_agent_tool_planner",
            "planner_used_llm": True,
            "selected_tool_uses_llm": tool_uses_llm(selected_tool_spec),
            "assigned_tools": [summarize_tool_for_planner(tool) for tool in candidate_tool_specs],
            "reason": str(payload.get("reason") or "LLM planner selected an assigned tool."),
            "risk_note": str(payload.get("risk_note") or ""),
            "raw_planner_payload": payload,
        }
    except Exception as exc:
        return fallback_selection(
            fallback_tool_spec=fallback_tool_spec,
            candidate_tool_specs=candidate_tool_specs,
            reason=f"LLM planner failed: {type(exc).__name__}: {exc}. {fallback_reason}",
            mode="llm_planner_error_fallback",
        )


def normalize_post_decision(value: Any) -> str:
    decision = str(value or "pass").strip().lower()
    return decision if decision in {"pass", "modify", "replan", "human_review"} else "pass"


def plan_agent_post_decision(
    *,
    agent_spec: dict[str, Any],
    contract: dict[str, Any],
    selected_tool_spec: dict[str, Any],
    tool_observation: dict[str, Any],
    state_summary: dict[str, Any],
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.agent_llm_planner_enabled:
        return {
            "planner_mode": "deterministic_planner_disabled",
            "planner_used_llm": False,
            "decision": "pass",
            "changed_output_intent": False,
            "reason": "LLM post-decision planner disabled.",
        }

    try:
        prompt = ChatPromptTemplate.from_messages([("system", POST_SYSTEM_PROMPT), ("human", POST_USER_PROMPT)])
        llm = get_chat_model(temperature=0.0, timeout=settings.agent_llm_planner_timeout_seconds)
        messages = prompt.format_messages(
            agent=compact_json(
                {
                    "id": agent_spec.get("id"),
                    "name": agent_spec.get("name"),
                    "role_prompt": agent_spec.get("role_prompt"),
                    "quality_checks": agent_spec.get("quality_checks", []),
                    "output_contract": agent_spec.get("output_contract", []),
                },
                max_chars=3500,
            ),
            contract=compact_json(contract, max_chars=2200),
            selected_tool=compact_json(summarize_tool_for_planner(selected_tool_spec), max_chars=1200),
            tool_observation=compact_json(tool_observation, max_chars=2500),
            state_summary=compact_json(state_summary, max_chars=2500),
        )
        response = invoke_chat_with_retry(llm, messages, retries=0)
        payload = extract_json_object(str(response.content))
        return {
            "planner_mode": "llm_agent_post_decider",
            "planner_used_llm": True,
            "decision": normalize_post_decision(payload.get("decision")),
            "changed_output_intent": bool(payload.get("changed_output_intent")),
            "reason": str(payload.get("reason") or "LLM post-decision completed."),
            "raw_post_payload": payload,
        }
    except Exception as exc:
        return {
            "planner_mode": "llm_post_decider_error_fallback",
            "planner_used_llm": False,
            "decision": "pass",
            "changed_output_intent": False,
            "reason": f"LLM post-decision planner failed: {type(exc).__name__}: {exc}",
        }
