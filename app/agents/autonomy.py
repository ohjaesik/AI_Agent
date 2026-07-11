# app/agents/autonomy.py
"""Supervisor Agent의 장기 목표 기반 자율 실행 정책을 담당한다.

이 파일은 실제 LLM 호출을 하지 않는다. 대신 Supervisor가 전체 workflow를
얼마나 자율적으로 밀고 갈 수 있는지, 어떤 경우에 한 번 더 반복해야 하는지,
어떤 경우에 사람 승인으로 넘겨야 하는지를 계산하는 순수 정책 함수들을 모아둔다.

주요 책임:
- 실행 시작 시 state에 들어갈 장기 목표(`supervisor_long_term_goal`) 생성
- extra loop, 비용 예산, loop 상한 같은 자율 실행 정책 생성
- stage별 필수 산출물이 비었는지 검사
- Expert Agent reflection과 산출물 상태를 합쳐 다음 loop 여부 결정
- 모든 판단을 `agent_autonomy_loop_decisions`에 남길 수 있는 trace payload 생성
"""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings


DEFAULT_LONG_TERM_OBJECTIVE = (
    "제조기업의 업무/문서/근거를 끝까지 검토해 AI Agent 도입 후보를 찾고, "
    "근거 기반 우선순위, PoC 계획, 보고서 산출물까지 사람 개입을 최소화해 완성한다."
)

# 자동화가 강해져도 넘지 않아야 하는 사람 승인 경계다.
# 이 목록은 runtime 정책과 prompt에 함께 들어가며, Supervisor가 "무엇은 자동으로
# 처리해도 되고 무엇은 책임자 판단이 필요한지"를 일관되게 보도록 한다.
DEFAULT_HUMAN_APPROVAL_BOUNDARIES = [
    "민감정보, 기밀정보, 고영향, 금지 가능 사용처럼 실제 책임 주체 확인이 필요한 경우",
    "근거가 심각하게 부족해 자동 분석 결과를 추천으로 확정하면 안 되는 경우",
    "운영 적용, 예산 집행, 조직 의사결정처럼 최종 business commitment가 필요한 경우",
    "사용자가 명시적으로 수동 검토 또는 중단을 요청한 경우",
]


# 각 Agent stage가 다음 stage로 handoff하기 전에 최소한 만들어야 하는 state key다.
# 값이 비어 있으면 Supervisor는 stage가 아직 목표를 달성하지 못했다고 보고,
# extra loop가 켜져 있고 예산/상한이 남아 있을 때 한 번 더 실행할 수 있다.
STAGE_REQUIRED_OUTPUTS: dict[str, list[str]] = {
    "context_evidence_agent": ["business_processes", "retrieved_contexts", "evidence_items", "used_sources"],
    "process_diagnosis_agent": ["process_analysis", "data_readiness", "automation_feasibility"],
    "governance_compliance_agent": ["risk_governance", "compliance_assessment"],
    "business_case_agent": ["roi_cost", "priority_ranking"],
    "evaluation_critic_agent": ["agent_evaluation"],
    "agent_replan": ["replan_request"],
    "delivery_orchestration_agent": ["human_review", "poc_plan", "report_data", "report_docx_path"],
}


def _safe_settings_attr(name: str, default: Any) -> Any:
    """설정 로딩 실패가 전체 agent 실행을 막지 않도록 안전하게 값을 읽는다."""

    try:
        return getattr(get_settings(), name, default)
    except Exception:
        return default


def _as_positive_int(value: Any, default: int) -> int:
    """환경변수/JSON 값처럼 타입이 흔들릴 수 있는 값을 양의 정수로 정규화한다."""

    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, parsed)


def _as_non_negative_float(value: Any, default: float) -> float:
    """비용 예산처럼 음수가 되면 안 되는 값을 0 이상의 float로 정규화한다."""

    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0.0, parsed)


def build_supervisor_long_term_goal(
    *,
    user_request: str | None,
    report_requirements: dict[str, Any] | None = None,
    explicit_goal: str | None = None,
) -> dict[str, Any]:
    """Supervisor가 전체 workflow 동안 붙잡고 있을 장기 목표를 만든다.

    각 stage prompt는 짧은 현재 작업만 보게 되기 쉽다. 그래서 장기 목표를
    state에 고정해 두고, Supervisor/Expert Agent가 매 루프마다 같은 목표와
    완료 기준을 참조하도록 한다.
    """

    objective = explicit_goal or user_request or DEFAULT_LONG_TERM_OBJECTIVE
    requirements = report_requirements or {}
    return {
        "objective": objective,
        "report_title": requirements.get("title"),
        "success_criteria": [
            "프로젝트/회사 context를 DB에서 로드한다.",
            "업무 후보별 RAG 근거와 citation source를 확보한다.",
            "업무 진단, 데이터 준비도, 자동화 가능성, 거버넌스/컴플라이언스, ROI를 비교한다.",
            "Evaluator와 LLM Critic이 근거 부족, 리스크, 추천 상태를 재검토한다.",
            "필요하면 Supervisor 통제 아래 bounded extra loop 또는 replan으로 근거를 보강한다.",
            "사람 승인이 꼭 필요한 경우만 interrupt하고, 그 외에는 PoC 계획과 DOCX 보고서까지 자동 산출한다.",
        ],
        "human_approval_boundaries": DEFAULT_HUMAN_APPROVAL_BOUNDARIES,
    }


def build_supervisor_autonomy_policy(*, extra_loop_enabled: bool) -> dict[str, Any]:
    """자율 실행의 범위, 예산, 반복 한계를 state에 남길 정책으로 정리한다.

    `Settings` 값은 실행 환경마다 없을 수 있으므로 `_safe_settings_attr`로 읽는다.
    이 정책은 prompt에도 들어가고, 실제 loop 판단 함수에서도 같은 값으로 쓰인다.
    그래서 LLM이 말하는 정책과 Python runtime이 적용하는 정책이 어긋나지 않는다.
    """

    max_stage_loops = _as_positive_int(
        _safe_settings_attr("supervisor_autonomous_max_stage_loops", 4),
        4,
    )
    extra_loop_budget = _as_positive_int(
        _safe_settings_attr("supervisor_autonomous_extra_loop_budget", 2),
        2,
    )
    cost_budget = _as_non_negative_float(
        _safe_settings_attr("supervisor_autonomous_cost_budget_usd", 1.5),
        1.5,
    )
    return {
        "enabled": bool(_safe_settings_attr("supervisor_autonomy_enabled", True)),
        "level": str(_safe_settings_attr("supervisor_autonomy_level", "controlled_high")),
        "extra_loop_enabled": bool(extra_loop_enabled),
        "max_stage_loops": max_stage_loops,
        "extra_loop_budget": extra_loop_budget,
        "cost_budget_usd": cost_budget,
        "auto_actions": [
            "load_project_data",
            "retrieve_rag_context",
            "run_diagnostic_scoring",
            "run_governance_screening",
            "run_roi_and_priority_ranking",
            "run_evaluator_and_llm_critic",
            "run_bounded_replan",
            "draft_report",
            "export_docx",
        ],
        "human_approval_boundaries": DEFAULT_HUMAN_APPROVAL_BOUNDARIES,
    }


def resolve_extra_loop_enabled(explicit_allow: bool | None) -> bool:
    """CLI/API 인자가 없으면 .env의 자율 실행 설정을 따른다.

    - `None`: 사용자가 명시하지 않았으므로 `.env`와 기본 자율성 정책을 따른다.
    - `True`: CLI/API에서 extra loop를 명시적으로 켠다.
    - `False`: 실험/디버깅을 위해 extra loop를 명시적으로 끈다.
    """

    settings_extra_loop = bool(_safe_settings_attr("agent_supervisor_extra_loop_enabled", True))
    autonomy_enabled = bool(_safe_settings_attr("supervisor_autonomy_enabled", True))
    if explicit_allow is None:
        return settings_extra_loop or autonomy_enabled
    return bool(explicit_allow)


def resolve_stage_loop_limit(state: dict[str, Any], *, default_base_limit: int = 2) -> int:
    """Supervisor stage가 몇 번까지 스스로 반복할 수 있는지 계산한다.

    기본 loop는 보수적으로 두고, `agent_supervisor_extra_loop_enabled`가 켜진
    경우에만 장기 목표 달성을 위한 추가 loop budget을 더한다. 그래도
    `SUPERVISOR_AUTONOMOUS_MAX_STAGE_LOOPS` 상한을 넘지 않는다.
    """

    configured_base = _as_positive_int(
        _safe_settings_attr("agent_supervisor_max_tool_loops", default_base_limit),
        default_base_limit,
    )
    policy = state.get("supervisor_autonomy_policy") or build_supervisor_autonomy_policy(
        extra_loop_enabled=bool(state.get("agent_supervisor_extra_loop_enabled")),
    )
    max_stage_loops = _as_positive_int(policy.get("max_stage_loops"), 4)
    base_limit = max(1, min(configured_base, max_stage_loops))

    state_has_extra_loop_flag = "agent_supervisor_extra_loop_enabled" in state
    extra_loop_enabled = (
        bool(state.get("agent_supervisor_extra_loop_enabled"))
        if state_has_extra_loop_flag
        else bool(policy.get("extra_loop_enabled"))
    )

    if not extra_loop_enabled:
        return base_limit

    extra_budget = _as_positive_int(policy.get("extra_loop_budget"), 2)
    return max(1, min(max_stage_loops, base_limit + extra_budget))


def estimate_recorded_llm_cost_usd(state: dict[str, Any], result: dict[str, Any] | None = None) -> float:
    """model decision trace에 기록된 예상 비용 합계를 계산한다.

    모델 선택은 `agent_model_decisions`에 여러 번 누적된다. 같은 decision이 state와
    stage result 양쪽에 중복으로 들어올 수 있으므로 문자열 marker로 한 번만 센다.
    실제 청구 비용이 아니라 router가 추정한 비용이며, loop stop-loss 용도다.
    """

    total = 0.0
    seen: set[str] = set()
    decisions = list(state.get("agent_model_decisions", []) or [])
    if result:
        decisions += list(result.get("agent_model_decisions", []) or [])
    for decision in decisions:
        if not isinstance(decision, dict):
            continue
        marker = str(decision.get("decision_id") or decision)
        if marker in seen:
            continue
        seen.add(marker)
        cost = decision.get("estimated_cost_usd")
        if cost is None:
            cost = (decision.get("cost_calculation") or {}).get("total_cost_usd")
        total += _as_non_negative_float(cost, 0.0)
    return round(total, 6)


def count_priority_statuses(state: dict[str, Any]) -> dict[str, int]:
    """추천 후보 상태를 집계해 Supervisor trace에 넣는다."""

    counts: dict[str, int] = {}
    for item in ((state.get("priority_ranking") or {}).get("items") or []):
        status = str(item.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def critical_output_gaps(stage_name: str, state: dict[str, Any], result: dict[str, Any]) -> list[str]:
    """stage가 handoff하기 전에 반드시 있어야 할 산출물 부족 신호를 찾는다.

    단순히 key 존재 여부만 보지 않고, stage 성격에 맞는 추가 검사를 함께 한다.
    예를 들어 Context/Evidence stage는 업무가 있는데 evidence/source가 0개면
    다음 stage가 분석할 근거가 없으므로 gap으로 본다.
    """

    merged = {**state, **result}
    gaps: list[str] = []

    for key in STAGE_REQUIRED_OUTPUTS.get(stage_name, []):
        if merged.get(key) in (None, {}, []):
            gaps.append(f"required_output_missing:{key}")

    process_count = len(merged.get("business_processes", []) or [])
    evidence_count = len(merged.get("evidence_items", []) or [])
    used_source_count = len(merged.get("used_sources", []) or [])
    priority_count = len(((merged.get("priority_ranking") or {}).get("items") or []))

    if stage_name == "context_evidence_agent" and process_count > 0:
        if evidence_count == 0:
            gaps.append("context_evidence_missing_for_all_processes")
        if used_source_count == 0:
            gaps.append("used_sources_missing")

    if stage_name in {"process_diagnosis_agent", "governance_compliance_agent"} and process_count > 0:
        for key in STAGE_REQUIRED_OUTPUTS.get(stage_name, []):
            summary = (merged.get(key) or {}).get("summary") if isinstance(merged.get(key), dict) else None
            # 일부 node는 실패해도 빈 summary dict를 만들 수 있다. process가 있는데
            # total_processes가 0이면 실제 분석이 비어 있다고 보고 loop 후보로 올린다.
            if isinstance(summary, dict) and int(summary.get("total_processes", process_count) or 0) == 0:
                gaps.append(f"{key}_summary_has_no_processes")

    if stage_name == "business_case_agent" and process_count > 0 and priority_count == 0:
        gaps.append("priority_ranking_has_no_candidates")

    if stage_name == "evaluation_critic_agent" and priority_count > 0:
        evaluation_count = len(((merged.get("agent_evaluation") or {}).get("items") or []))
        if evaluation_count == 0:
            gaps.append("agent_evaluation_has_no_items")

    if stage_name == "delivery_orchestration_agent" and not merged.get("report_docx_path"):
        gaps.append("report_docx_path_missing")

    return gaps


def build_supervisor_loop_decision(
    *,
    stage_name: str,
    agent_id: str,
    loop_index: int,
    loop_limit: int,
    state: dict[str, Any],
    result: dict[str, Any],
    reflection: dict[str, Any],
) -> dict[str, Any]:
    """Supervisor가 현재 stage를 한 번 더 돌릴지 판단하고 감사 trace를 만든다.

    판단 순서:
    1. 현재 state/result를 합쳐 stage 산출물 부족을 찾는다.
    2. Expert Agent reflection이 `iterate` 또는 `needs_iteration=true`를 냈는지 본다.
    3. 비용 예산, extra loop enable 여부, loop 상한을 stop-loss로 적용한다.
    4. 반복할 이유가 있고 막는 이유가 없을 때만 `should_iterate=true`를 낸다.

    중요한 점은 "비용 예산을 넘었다"는 사실만으로 stage를 실패 처리하지 않는다는 것.
    반복할 이유가 없으면 그대로 handoff가 맞고, 반복할 이유가 있을 때만 비용 예산이
    반복을 막는 사유가 된다.
    """

    merged = {**state, **result}
    goal = merged.get("supervisor_long_term_goal") or build_supervisor_long_term_goal(
        user_request=merged.get("user_request"),
        report_requirements=merged.get("report_requirements"),
    )
    policy = merged.get("supervisor_autonomy_policy") or build_supervisor_autonomy_policy(
        extra_loop_enabled=bool(merged.get("agent_supervisor_extra_loop_enabled")),
    )
    output_gaps = critical_output_gaps(stage_name, state, result)
    reflection_decision = str(reflection.get("decision") or "handoff")
    reflection_wants_iteration = bool(reflection.get("needs_iteration")) or reflection_decision == "iterate"
    iteration_reasons: list[str] = []

    if reflection_wants_iteration:
        iteration_reasons.append(str(reflection.get("reason") or "expert_reflection_requested_iteration"))
    iteration_reasons.extend(output_gaps)

    estimated_cost = estimate_recorded_llm_cost_usd(state, result)
    cost_budget = _as_non_negative_float(policy.get("cost_budget_usd"), 0.0)
    blocking_reasons: list[str] = []

    if not bool(policy.get("enabled", True)):
        blocking_reasons.append("supervisor_autonomy_disabled")
    if not bool(merged.get("agent_supervisor_extra_loop_enabled")):
        blocking_reasons.append("extra_loop_not_enabled")
    if cost_budget > 0 and estimated_cost >= cost_budget:
        blocking_reasons.append("autonomy_cost_budget_reached")
    if loop_index >= loop_limit and iteration_reasons:
        blocking_reasons.append("stage_loop_limit_reached")

    should_iterate = bool(iteration_reasons) and not blocking_reasons and loop_index < loop_limit
    # decision은 사람이 workflow_state를 읽을 때 가장 먼저 보는 요약값이다.
    # 그래서 실제 반복 필요가 없으면 cost budget warning이 있어도 handoff로 남긴다.
    if should_iterate:
        decision = "iterate"
    elif iteration_reasons and "stage_loop_limit_reached" in blocking_reasons:
        decision = "loop_limit_reached"
    elif iteration_reasons and "autonomy_cost_budget_reached" in blocking_reasons:
        decision = "stop_for_cost_budget"
    else:
        decision = "handoff"

    return {
        "supervisor_agent_id": "ax_delivery_supervisor_agent",
        "stage_name": stage_name,
        "agent_id": agent_id,
        "loop_index": loop_index,
        "loop_limit": loop_limit,
        "decision": decision,
        "should_iterate": should_iterate,
        "long_term_goal": goal.get("objective"),
        "autonomy_level": policy.get("level"),
        "iteration_reasons": iteration_reasons,
        "blocking_reasons": blocking_reasons,
        "critical_output_gaps": output_gaps,
        "reflection_decision": reflection_decision,
        "reflection_needs_iteration": bool(reflection.get("needs_iteration")),
        "estimated_recorded_llm_cost_usd": estimated_cost,
        "cost_budget_usd": cost_budget,
        "priority_status_counts": count_priority_statuses(merged),
        "progress_snapshot": {
            "business_processes": len(merged.get("business_processes", []) or []),
            "documents": len(merged.get("documents", []) or []),
            "evidence_items": len(merged.get("evidence_items", []) or []),
            "used_sources": len(merged.get("used_sources", []) or []),
            "priority_candidates": len(((merged.get("priority_ranking") or {}).get("items") or [])),
            "has_human_review": bool(merged.get("human_review")),
            "has_report_docx": bool(merged.get("report_docx_path")),
            "error_count": len(merged.get("errors", []) or []),
        },
        "human_approval_boundaries": policy.get("human_approval_boundaries", DEFAULT_HUMAN_APPROVAL_BOUNDARIES),
    }
