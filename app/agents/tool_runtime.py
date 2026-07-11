# app/agents/tool_runtime.py

"""Agent tool 호출을 표준 trace와 함께 실행하는 runtime.

tool 실행 시작/성공/실패 audit log를 남기고, runner 함수 결과를 Agent loop가
소비할 수 있는 일관된 구조로 포장한다.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.agents.registry import get_agent_spec
from app.agents.tool_guard import assert_tool_spec_allowed


@dataclass(frozen=True)
class ToolCallResult:
    """tool 실행 결과, audit log, 관찰 정보를 함께 운반하는 값 객체다."""
    result: dict[str, Any]
    audit_logs: list[dict[str, Any]] = field(default_factory=list)
    observation: dict[str, Any] = field(default_factory=dict)


def utc_now() -> str:
    """UTC ISO timestamp를 생성해 audit log의 공통 시간값으로 사용한다."""
    return datetime.now(timezone.utc).isoformat()


def compact_json(value: Any, max_chars: int = 900) -> str:
    """compact_json 함수. Agent tool 호출을 표준 trace와 함께 실행하는 runtime. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    try:
        text = json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)
    except TypeError:
        text = str(value)
    return text if len(text) <= max_chars else text[:max_chars] + "..."


def is_langgraph_interrupt(exc: BaseException) -> bool:
    """is_langgraph_interrupt 함수. 조건을 검사해 True/False 판단값을 반환한다."""
    name = type(exc).__name__.lower()
    module = type(exc).__module__.lower()
    return "interrupt" in name and "langgraph" in module


def summarize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """tool 호출 입력 payload를 trace에 넣기 좋은 작은 요약으로 줄인다."""
    state = payload.get("state") if isinstance(payload, dict) else None
    if not isinstance(state, dict):
        return {"payload": compact_json(payload)}

    return {
        "project_id": state.get("project_id"),
        "company_id": state.get("company_id"),
        "business_processes": len(state.get("business_processes", []) or []),
        "documents": len(state.get("documents", []) or []),
        "evidence_items": len(state.get("evidence_items", []) or []),
        "priority_items": len((state.get("priority_ranking", {}) or {}).get("items", []) or []),
        "state_keys": sorted(state.keys())[:40],
    }


def summarize_result(result: dict[str, Any]) -> dict[str, Any]:
    """tool 실행 결과를 trace에 넣기 좋은 작은 요약으로 줄인다."""
    return {
        "result_keys": sorted(result.keys()),
        "errors_returned": len(result.get("errors", []) or []),
        "audit_logs_returned": len(result.get("audit_logs", []) or []),
        "result_preview": compact_json({key: value for key, value in result.items() if key not in {"audit_logs"}}, max_chars=700),
    }


def build_tool_audit_log(
    *,
    node_name: str | None,
    agent_id: str,
    tool_name: str,
    call_id: str,
    status: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """tool 실행 시작/성공/실패 이벤트를 audit log 형식으로 만든다."""
    return {
        "node": node_name or tool_name,
        "status": status,
        "timestamp": utc_now(),
        "payload": {
            "agent_id": agent_id,
            "tool_name": tool_name,
            "tool_call_id": call_id,
            **(payload or {}),
        },
    }


def call_agent_tool(
    *,
    agent_id: str,
    tool_name: str,
    payload: dict[str, Any],
    runner: Callable[[dict[str, Any]], dict[str, Any]],
    node_name: str | None = None,
) -> ToolCallResult:
    """Execute a tool through the Agent Registry contract.

    The caller supplies the concrete runner so existing deterministic/RAG/LLM node
    implementations can be reused while still flowing through a tool-calling gate.
    """
    agent_spec = get_agent_spec(agent_id)
    if not agent_spec:
        raise ValueError(f"Unknown agent_id: {agent_id}")

    tool_spec = assert_tool_spec_allowed(agent_id=agent_id, tool_name=tool_name)
    call_id = str(uuid4())

    start_log = build_tool_audit_log(
        node_name=node_name,
        agent_id=agent_id,
        tool_name=tool_name,
        call_id=call_id,
        status="agent_tool_call_started",
        payload={
            "agent_name": agent_spec.get("name"),
            "tool_description": tool_spec.get("description"),
            "input_schema": tool_spec.get("input_schema"),
            "payload_summary": summarize_payload(payload),
        },
    )

    try:
        result = runner(payload)
        observation = summarize_result(result)
        success_log = build_tool_audit_log(
            node_name=node_name,
            agent_id=agent_id,
            tool_name=tool_name,
            call_id=call_id,
            status="agent_tool_call_succeeded",
            payload={
                "output_schema": tool_spec.get("output_schema"),
                "observation": observation,
            },
        )
        return ToolCallResult(result=result, audit_logs=[start_log, success_log], observation=observation)
    except BaseException as exc:
        if is_langgraph_interrupt(exc):
            raise
        build_tool_audit_log(
            node_name=node_name,
            agent_id=agent_id,
            tool_name=tool_name,
            call_id=call_id,
            status="agent_tool_call_failed",
            payload={
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
        raise RuntimeError(f"Agent tool call failed: agent={agent_id}, tool={tool_name}, node={node_name}") from exc
