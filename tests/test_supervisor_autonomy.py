"""Supervisor 장기 목표 기반 자율 loop 판단과 비용 stop-loss를 검증한다.
"""

from __future__ import annotations

from app.agents.autonomy import (
    build_supervisor_autonomy_policy,
    build_supervisor_loop_decision,
    resolve_extra_loop_enabled,
    resolve_stage_loop_limit,
)


def test_extra_loop_defaults_to_supervisor_autonomy() -> None:
    assert resolve_extra_loop_enabled(None) is True
    assert resolve_extra_loop_enabled(False) is False
    assert resolve_extra_loop_enabled(True) is True


def test_stage_loop_limit_uses_bounded_extra_budget() -> None:
    state = {
        "agent_supervisor_extra_loop_enabled": True,
        "supervisor_autonomy_policy": build_supervisor_autonomy_policy(extra_loop_enabled=True),
    }

    assert resolve_stage_loop_limit(state, default_base_limit=2) == 4


def test_supervisor_loop_decision_iterates_when_required_output_is_missing() -> None:
    state = {
        "agent_supervisor_extra_loop_enabled": True,
        "supervisor_autonomy_policy": build_supervisor_autonomy_policy(extra_loop_enabled=True),
        "business_processes": [{"id": 1, "name": "계약 검토"}],
    }

    decision = build_supervisor_loop_decision(
        stage_name="business_case_agent",
        agent_id="business_case_agent",
        loop_index=1,
        loop_limit=4,
        state=state,
        result={},
        reflection={"decision": "handoff", "needs_iteration": False},
    )

    assert decision["decision"] == "iterate"
    assert decision["should_iterate"] is True
    assert "required_output_missing:priority_ranking" in decision["iteration_reasons"]


def test_supervisor_loop_decision_handoffs_when_extra_loop_is_disabled() -> None:
    state = {
        "agent_supervisor_extra_loop_enabled": False,
        "supervisor_autonomy_policy": build_supervisor_autonomy_policy(extra_loop_enabled=False),
        "business_processes": [{"id": 1, "name": "계약 검토"}],
    }

    decision = build_supervisor_loop_decision(
        stage_name="business_case_agent",
        agent_id="business_case_agent",
        loop_index=1,
        loop_limit=2,
        state=state,
        result={},
        reflection={"decision": "iterate", "needs_iteration": True, "reason": "ranking missing"},
    )

    assert decision["decision"] == "handoff"
    assert decision["should_iterate"] is False
    assert "extra_loop_not_enabled" in decision["blocking_reasons"]


def test_supervisor_loop_decision_does_not_stop_for_cost_without_iteration_need() -> None:
    state = {
        "agent_supervisor_extra_loop_enabled": True,
        "supervisor_autonomy_policy": {
            **build_supervisor_autonomy_policy(extra_loop_enabled=True),
            "cost_budget_usd": 0.01,
        },
        "agent_model_decisions": [
            {
                "decision_id": "expensive-call",
                "estimated_cost_usd": 0.02,
            }
        ],
        "replan_request": {"attempt": 1},
    }

    decision = build_supervisor_loop_decision(
        stage_name="agent_replan",
        agent_id="evaluation_critic_agent",
        loop_index=1,
        loop_limit=4,
        state=state,
        result={"replan_request": {"attempt": 1}},
        reflection={"decision": "handoff", "needs_iteration": False},
    )

    assert decision["decision"] == "handoff"
    assert decision["should_iterate"] is False
    assert "autonomy_cost_budget_reached" in decision["blocking_reasons"]
