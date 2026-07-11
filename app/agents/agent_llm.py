# app/agents/agent_llm.py
"""Expert Agent의 command/reflection LLM 호출을 담당한다.

Supervisor가 "이 stage는 어떤 목표와 tool policy로 실행하라"는 위임장을 만들면,
각 Expert Agent는 두 번의 LLM 판단을 한다.

1. command prompt
   - 할당된 내부 node 목록과 tool 목록을 보고 실행 순서를 정한다.
   - runtime은 이 순서를 참고하되, 허용되지 않은 node/tool은 실행하지 않는다.

2. reflection prompt
   - 내부 node 실행 후 결과를 보고 handoff/iterate/replan/human_review 여부를 판단한다.
   - 실제 반복 여부는 Supervisor autonomy policy가 다시 검증한다.

LLM 호출이 timeout되면 더 강한 모델로 재시도하고, 실패 trace는 `agent_llm_calls`와
`agent_model_decisions`에 남긴다. LLM이 끝내 실패해도 deterministic fallback으로
stage 실행은 이어진다.
"""

from __future__ import annotations

from typing import Any

from langchain_core.prompts import ChatPromptTemplate

from app.agents.agent_contract import sanitize_node_order
from app.agents.model_router import compact_model_assignment, select_escalation_model
from app.agents.registry import get_tool_specs_for_node
from app.core.llm import get_chat_model, invoke_chat_with_retry
from app.core.llm_json import compact_json, extract_json_object
from app.core.model_policy import (
    is_model_availability_exception,
    is_timeout_exception,
    retry_status_for_exception,
    retry_timeout_seconds,
    safe_model_retry_count,
    safe_model_retry_timeout_multiplier,
    safe_model_timeout,
)

SYSTEM_PROMPT = """
You are one Expert Agent inside an AX Delivery Supervisor workflow.
You do not answer the user directly.
You receive a delegated task from the Supervisor Agent, inspect the handoff context, decide how to run your assigned internal nodes/tools, and return a machine-readable command.

Rules:
- Use only the assigned internal nodes and assigned tools shown in the prompt.
- Follow the Supervisor Agent delegation, node order, tool priorities, and approval policy unless it conflicts with safety controls.
- Do not invent tools, APIs, files, or data.
- Keep the decision grounded in the provided state summary and handoff payload.
- Return JSON only.
""".strip()

# Expert Agent가 "실행 전 계획"을 JSON으로 반환하도록 하는 prompt다.
# Supervisor delegation, Agent contract, handoff context, 장기 목표를 함께 넣어
# 단순 node 순서가 아니라 "왜 이 순서로 실행하는지"까지 trace에 남긴다.
COMMAND_PROMPT = """
Supervisor delegation:
{delegation}

Expert Agent contract:
{agent_contract}

Assigned internal nodes and tools:
{assigned_work}

Incoming handoff context:
{handoff_context}

Current state summary:
{state_summary}

Supervisor long-term goal and autonomy policy:
{autonomy_context}

Return JSON only:
{{
  "agent_intent": "what this Agent will accomplish in Korean",
  "node_order": ["assigned_node_name_1", "assigned_node_name_2"],
  "node_commands": [
    {{
      "node_name": "assigned node name",
      "instruction": "Korean instruction for this internal node",
      "expected_output": "expected artifact/result",
      "tool_focus": ["assigned tool name"]
    }}
  ],
  "handoff_plan": {{
    "next_agent": "downstream Agent or final_output",
    "payload_keys": ["state keys to hand off"],
    "reason": "Korean handoff reason"
  }},
  "needs_iteration": false,
  "risk_note": "Korean risk/control note"
}}
""".strip()

REFLECT_SYSTEM_PROMPT = """
You are the same Expert Agent after running assigned internal nodes and tools.
Observe the produced result, decide whether the Agent stage is sufficient, and define the downstream handoff.
Return JSON only.
""".strip()

# Expert Agent가 "실행 후 관찰"을 JSON으로 반환하도록 하는 prompt다.
# 이 결과의 `needs_iteration`은 곧바로 반복을 의미하지 않고, Supervisor autonomy
# 판단 함수가 비용/상한/필수 산출물과 함께 한 번 더 검증한다.
REFLECT_PROMPT = """
Supervisor delegation:
{delegation}

Expert Agent contract:
{agent_contract}

Original Agent command:
{agent_command}

Executed internal nodes:
{executed_nodes}

Result summary:
{result_summary}

Available output keys:
{available_output_keys}

Supervisor long-term goal and autonomy policy:
{autonomy_context}

Return JSON only:
{{
  "decision": "handoff|iterate|human_review|replan|stop",
  "needs_iteration": false,
  "reason": "Korean reason",
  "handoff_plan": {{
    "next_agent": "downstream Agent or final_output",
    "payload_keys": ["state keys to hand off"],
    "reason": "Korean handoff reason"
  }},
  "quality_checks": ["short check result"],
  "risk_note": "Korean risk/control note"
}}
""".strip()

class AgentLLMInvocationError(Exception):
    """LLM 호출 실패와 retry trace를 함께 운반한다."""

    def __init__(
        self,
        message: str,
        *,
        retry_attempts: list[dict[str, Any]],
        model_retry_assignments: list[dict[str, Any]],
        final_model_assignment: dict[str, Any] | None,
    ) -> None:
        super().__init__(message)
        self.retry_attempts = retry_attempts
        self.model_retry_assignments = model_retry_assignments
        self.final_model_assignment = final_model_assignment


def invoke_chat_with_timeout_escalation(
    *,
    messages: list[Any],
    model_assignment: dict[str, Any] | None,
    agent_id: str,
    stage_name: str,
    call_kind: str,
    state: dict[str, Any],
) -> tuple[Any, dict[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]]]:
    """timeout 또는 모델 접근 실패면 모델을 상향/대체해 재시도하고 모든 시도를 trace로 반환한다.

    반환값:
    - response: 최종 LLM 응답
    - final_model_assignment: 성공한 시도의 모델 배정
    - model_retry_assignments: retry 과정에서 새로 선택된 모델들
    - retry_attempts: 각 시도의 timeout, status, error trace

    timeout과 model-not-found/access 오류는 다른 후보로 해결될 수 있으므로 재시도한다.
    그 외 인증 오류, prompt 오류, provider 내부 오류는 호출부가 deterministic
    fallback command/reflection을 만들도록 즉시 예외로 올린다.
    """

    retry_attempts: list[dict[str, Any]] = []
    model_retry_assignments: list[dict[str, Any]] = []
    attempt_model_assignment = model_assignment
    max_attempts = safe_model_retry_count("agent", default=1) + 1
    base_timeout = safe_model_timeout("agent", default=8.0)
    timeout_multiplier = safe_model_retry_timeout_multiplier("agent", default=1.6)

    for attempt_index in range(1, max_attempts + 1):
        timeout_seconds = retry_timeout_seconds(base_timeout, timeout_multiplier, attempt_index)
        try:
            llm = get_chat_model(temperature=0.0, timeout=timeout_seconds, model_assignment=attempt_model_assignment)
            response = invoke_chat_with_retry(llm, messages, retries=0)
            retry_attempts.append(
                {
                    "attempt": attempt_index,
                    "status": "success",
                    "timeout_seconds": timeout_seconds,
                    "model_selection": compact_model_assignment(attempt_model_assignment),
                }
            )
            return response, attempt_model_assignment, model_retry_assignments, retry_attempts
        except Exception as exc:
            error_text = f"{type(exc).__name__}: {exc}"
            timed_out = is_timeout_exception(exc)
            model_unavailable = is_model_availability_exception(exc)
            retry_attempts.append(
                {
                    "attempt": attempt_index,
                    "status": retry_status_for_exception(exc),
                    "timeout_seconds": timeout_seconds,
                    "model_selection": compact_model_assignment(attempt_model_assignment),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            if not (timed_out or model_unavailable) or attempt_index >= max_attempts:
                raise AgentLLMInvocationError(
                    error_text,
                    retry_attempts=retry_attempts,
                    model_retry_assignments=model_retry_assignments,
                    final_model_assignment=attempt_model_assignment,
                ) from exc

            attempt_model_assignment = select_escalation_model(
                agent_id=agent_id,
                stage_name=stage_name,
                call_kind=call_kind,
                state=state,
                previous_assignment=attempt_model_assignment,
                failure_reason=error_text,
            )
            model_retry_assignments.append(attempt_model_assignment)

    raise AgentLLMInvocationError(
        "Agent LLM retry loop ended without a response.",
        retry_attempts=retry_attempts,
        model_retry_assignments=model_retry_assignments,
        final_model_assignment=attempt_model_assignment,
    )


def summarize_state(state: dict[str, Any]) -> dict[str, Any]:
    """Agent prompt에 넣을 현재 state 요약을 만든다."""

    return {
        "project_id": state.get("project_id"),
        "company_id": state.get("company_id"),
        "user_request": state.get("user_request"),
        "business_process_count": len(state.get("business_processes", []) or []),
        "document_count": len(state.get("documents", []) or []),
        "evidence_item_count": len(state.get("evidence_items", []) or []),
        "used_source_count": len(state.get("used_sources", []) or []),
        "priority_candidate_count": len((state.get("priority_ranking", {}) or {}).get("items", []) or []),
        "has_replan_request": bool(state.get("replan_request")),
        "has_human_review": bool(state.get("human_review")),
        "has_report_data": bool(state.get("report_data")),
        "supervisor_long_term_goal": state.get("supervisor_long_term_goal"),
        "supervisor_autonomy_policy": state.get("supervisor_autonomy_policy"),
        "available_keys": sorted(state.keys()),
    }


def summarize_result(result: dict[str, Any]) -> dict[str, Any]:
    """reflection prompt가 볼 stage 실행 결과 요약을 만든다."""

    summary: dict[str, Any] = {
        "output_keys": sorted(k for k, v in result.items() if v not in (None, {}, [])),
        "errors": result.get("errors", []),
        "agent_tool_call_count": len(result.get("agent_tool_calls", []) or []),
        "agent_decision_count": len(result.get("agent_decisions", []) or []),
    }
    if result.get("priority_ranking"):
        summary["priority_summary"] = (result.get("priority_ranking") or {}).get("summary", {})
    if result.get("agent_evaluation"):
        summary["evaluation_summary"] = (result.get("agent_evaluation") or {}).get("summary", {})
    if result.get("poc_plan"):
        summary["poc_summary"] = {
            "mvp_agent": (result.get("poc_plan") or {}).get("mvp_agent", {}),
            "requires_human_review_followup": (result.get("poc_plan") or {}).get("requires_human_review_followup"),
        }
    if result.get("report_docx_path"):
        summary["report_docx_path"] = result.get("report_docx_path")
    return summary


def assigned_work_for_nodes(agent_id: str, internal_nodes: list[str]) -> list[dict[str, Any]]:
    """Agent가 사용할 수 있는 내부 node와 tool 목록을 prompt용 catalog로 만든다."""

    work = []
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
                        "uses_llm": bool(tool.get("uses_llm")) or "llm" in str(tool.get("name", "")).lower(),
                    }
                    for tool in tools
                ],
            }
        )
    return work

def fallback_agent_command(
    *,
    agent_id: str,
    stage_name: str,
    internal_nodes: list[str],
    reason: str,
    model_assignment: dict[str, Any] | None = None,
    retry_attempts: list[dict[str, Any]] | None = None,
    model_retry_assignments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """command LLM 실패 시 사용할 기본 실행 계획을 만든다."""

    return {
        "agent_id": agent_id,
        "stage_name": stage_name,
        "llm_used": False,
        "mode": "deterministic_fallback_agent_command",
        "agent_intent": f"{agent_id} stage를 고정 순서로 수행한다.",
        "node_order": internal_nodes,
        "node_commands": [
            {
                "node_name": node_name,
                "instruction": f"{node_name} 내부 node를 실행하고 산출물을 다음 Agent에 넘길 수 있게 정리한다.",
                "expected_output": "node result and trace metadata",
                "tool_focus": [],
            }
            for node_name in internal_nodes
        ],
        "handoff_plan": {},
        "needs_iteration": False,
        "risk_note": reason,
        "reason": reason,
        "model_selection": compact_model_assignment(model_assignment),
        "retry_attempts": retry_attempts or [],
        "model_retry_assignments": model_retry_assignments or [],
    }


def run_agent_command_prompt(
    *,
    agent_spec: dict[str, Any],
    stage_name: str,
    internal_nodes: list[str],
    state: dict[str, Any],
    incoming_handoffs: list[dict[str, Any]] | None = None,
    loop_index: int = 1,
    model_assignment: dict[str, Any] | None = None,
    supervisor_delegation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Expert Agent command LLM을 호출해 내부 node 실행 계획을 만든다.

    이 함수는 실행 자체를 하지 않는다. 반환된 `node_order`와 `node_commands`는
    workflow runtime이 읽어 실제 내부 node를 실행한다. LLM 실패 시에도 기본
    node 순서로 fallback하므로 전체 graph는 계속 진행된다.
    """

    agent_id = str(agent_spec.get("id") or stage_name)
    try:
        prompt = ChatPromptTemplate.from_messages([("system", SYSTEM_PROMPT), ("human", COMMAND_PROMPT)])
        messages = prompt.format_messages(
            delegation=compact_json(
                {
                    "supervisor_agent_id": "ax_delivery_supervisor_agent",
                    "delegated_to": agent_id,
                    "stage_name": stage_name,
                    "loop_index": loop_index,
                    "supervisor_delegation": supervisor_delegation or {},
                },
                max_chars=3600,
            ),
            agent_contract=compact_json(
                {
                    "id": agent_spec.get("id"),
                    "name": agent_spec.get("name"),
                    "role_prompt": agent_spec.get("role_prompt"),
                    "task_instructions": agent_spec.get("task_instructions", []),
                    "quality_checks": agent_spec.get("quality_checks", []),
                    "output_contract": agent_spec.get("output_contract", []),
                    "handoff_notes": agent_spec.get("handoff_notes", []),
                },
                max_chars=5000,
            ),
            assigned_work=compact_json(assigned_work_for_nodes(agent_id, internal_nodes), max_chars=4500),
            handoff_context=compact_json(incoming_handoffs or [], max_chars=3000),
            state_summary=compact_json(summarize_state(state), max_chars=3000),
            autonomy_context=compact_json(
                {
                    "long_term_goal": state.get("supervisor_long_term_goal"),
                    "autonomy_policy": state.get("supervisor_autonomy_policy"),
                    "supervisor_iteration_policy": (supervisor_delegation or {}).get("iteration_policy", {}),
                    "long_term_goal_alignment": (supervisor_delegation or {}).get("long_term_goal_alignment"),
                },
                max_chars=2600,
            ),
        )
        response, final_model_assignment, retry_assignments, retry_attempts = invoke_chat_with_timeout_escalation(
            messages=messages,
            model_assignment=model_assignment,
            agent_id=agent_id,
            stage_name=stage_name,
            call_kind="agent_command",
            state=state,
        )
        payload = extract_json_object(str(response.content))
        payload["node_order"] = sanitize_node_order(payload.get("node_order"), internal_nodes)
        return {
            "agent_id": agent_id,
            "stage_name": stage_name,
            "llm_used": True,
            "mode": "expert_agent_llm_command",
            "loop_index": loop_index,
            "model_selection": compact_model_assignment(final_model_assignment),
            "retry_attempts": retry_attempts,
            "model_retry_assignments": retry_assignments,
            **payload,
        }
    except AgentLLMInvocationError as exc:
        return fallback_agent_command(
            agent_id=agent_id,
            stage_name=stage_name,
            internal_nodes=internal_nodes,
            reason=f"Agent LLM command failed: {exc}",
            model_assignment=exc.final_model_assignment,
            retry_attempts=exc.retry_attempts,
            model_retry_assignments=exc.model_retry_assignments,
        )
    except Exception as exc:
        return fallback_agent_command(
            agent_id=agent_id,
            stage_name=stage_name,
            internal_nodes=internal_nodes,
            reason=f"Agent LLM command failed: {type(exc).__name__}: {exc}",
            model_assignment=model_assignment,
        )


def fallback_agent_reflection(
    *,
    agent_id: str,
    stage_name: str,
    reason: str,
    model_assignment: dict[str, Any] | None = None,
    retry_attempts: list[dict[str, Any]] | None = None,
    model_retry_assignments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """reflection LLM 실패 시 handoff를 계속하기 위한 기본 판단을 만든다."""

    return {
        "agent_id": agent_id,
        "stage_name": stage_name,
        "llm_used": False,
        "mode": "deterministic_fallback_agent_reflection",
        "decision": "handoff",
        "needs_iteration": False,
        "reason": reason,
        "handoff_plan": {},
        "quality_checks": ["LLM reflection unavailable; deterministic handoff continues."],
        "risk_note": reason,
        "model_selection": compact_model_assignment(model_assignment),
        "retry_attempts": retry_attempts or [],
        "model_retry_assignments": model_retry_assignments or [],
    }


def run_agent_reflection_prompt(
    *,
    agent_spec: dict[str, Any],
    stage_name: str,
    agent_command: dict[str, Any],
    executed_nodes: list[str],
    state: dict[str, Any],
    result: dict[str, Any],
    loop_index: int = 1,
    model_assignment: dict[str, Any] | None = None,
    supervisor_delegation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Expert Agent reflection LLM을 호출해 stage 결과의 충분성을 판단한다.

    reflection은 "Agent 자신의 의견"이다. 최종 반복 여부는
    `build_supervisor_loop_decision`에서 다시 판단하므로, LLM이 무조건 iterate를
    요구해도 비용/상한/산출물 상태에 따라 handoff될 수 있다.
    """

    agent_id = str(agent_spec.get("id") or stage_name)
    try:
        prompt = ChatPromptTemplate.from_messages([("system", REFLECT_SYSTEM_PROMPT), ("human", REFLECT_PROMPT)])
        messages = prompt.format_messages(
            delegation=compact_json(
                {
                    "supervisor_agent_id": "ax_delivery_supervisor_agent",
                    "delegated_to": agent_id,
                    "stage_name": stage_name,
                    "loop_index": loop_index,
                    "supervisor_delegation": supervisor_delegation or {},
                },
                max_chars=3600,
            ),
            agent_contract=compact_json(
                {
                    "id": agent_spec.get("id"),
                    "name": agent_spec.get("name"),
                    "role_prompt": agent_spec.get("role_prompt"),
                    "quality_checks": agent_spec.get("quality_checks", []),
                    "output_contract": agent_spec.get("output_contract", []),
                    "handoff_notes": agent_spec.get("handoff_notes", []),
                },
                max_chars=4200,
            ),
            agent_command=compact_json(agent_command, max_chars=2600),
            executed_nodes=compact_json(executed_nodes, max_chars=800),
            result_summary=compact_json(summarize_result(result), max_chars=3600),
            available_output_keys=compact_json(sorted(k for k, v in {**state, **result}.items() if v not in (None, {}, [])), max_chars=2500),
            autonomy_context=compact_json(
                {
                    "long_term_goal": state.get("supervisor_long_term_goal"),
                    "autonomy_policy": state.get("supervisor_autonomy_policy"),
                    "supervisor_iteration_policy": (supervisor_delegation or {}).get("iteration_policy", {}),
                    "reflection_instruction": (
                        "needs_iteration=true는 같은 stage를 한 번 더 실행하면 산출물 부족이나 실패가 실제로 개선될 때만 사용한다. "
                        "새 출처 수집이 필요한 근거 부족은 replan, 책임자 판단이 필요한 위험은 human_review로 보낸다."
                    ),
                },
                max_chars=2800,
            ),
        )
        response, final_model_assignment, retry_assignments, retry_attempts = invoke_chat_with_timeout_escalation(
            messages=messages,
            model_assignment=model_assignment,
            agent_id=agent_id,
            stage_name=stage_name,
            call_kind="agent_reflection",
            state={**state, **result},
        )
        payload = extract_json_object(str(response.content))
        return {
            "agent_id": agent_id,
            "stage_name": stage_name,
            "llm_used": True,
            "mode": "expert_agent_llm_reflection",
            "loop_index": loop_index,
            "model_selection": compact_model_assignment(final_model_assignment),
            "retry_attempts": retry_attempts,
            "model_retry_assignments": retry_assignments,
            **payload,
        }
    except AgentLLMInvocationError as exc:
        return fallback_agent_reflection(
            agent_id=agent_id,
            stage_name=stage_name,
            reason=f"Agent LLM reflection failed: {exc}",
            model_assignment=exc.final_model_assignment,
            retry_attempts=exc.retry_attempts,
            model_retry_assignments=exc.model_retry_assignments,
        )
    except Exception as exc:
        return fallback_agent_reflection(
            agent_id=agent_id,
            stage_name=stage_name,
            reason=f"Agent LLM reflection failed: {type(exc).__name__}: {exc}",
            model_assignment=model_assignment,
        )


def build_agent_llm_call_record(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """command/reflection payload를 UI와 workflow_state에서 보기 쉬운 trace로 줄인다."""

    return {
        "kind": kind,
        "agent_id": payload.get("agent_id"),
        "stage_name": payload.get("stage_name"),
        "loop_index": payload.get("loop_index", 1),
        "llm_used": bool(payload.get("llm_used")),
        "mode": payload.get("mode"),
        "decision": payload.get("decision"),
        "node_order": payload.get("node_order"),
        "needs_iteration": bool(payload.get("needs_iteration")),
        "reason": payload.get("reason") or payload.get("agent_intent"),
        "handoff_plan": payload.get("handoff_plan", {}),
        "risk_note": payload.get("risk_note"),
        "model_selection": payload.get("model_selection", {}),
        "retry_attempts": payload.get("retry_attempts", []),
        "model_retry_assignments": payload.get("model_retry_assignments", []),
    }
