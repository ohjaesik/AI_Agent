"""Supervisor 고정 모델, Expert Agent 비용/성능 라우팅, timeout escalation을 검증한다.
"""

from __future__ import annotations

import json

from app.agents.model_router import SUPERVISOR_AGENT_ID, select_agent_model, select_escalation_model
from app.core.config import get_settings
from app.core.llm import is_model_availability_exception


def reset_settings(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/db")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("VLLM_MODEL", "gemma-4-e4b-it")
    monkeypatch.delenv("OPENAI_EXTRA_MODEL_PROFILES_JSON", raising=False)
    get_settings.cache_clear()


def test_supervisor_uses_configured_upper_model(monkeypatch):
    reset_settings(monkeypatch)
    monkeypatch.setenv("SUPERVISOR_MODEL_PROVIDER", "openai")
    monkeypatch.setenv("SUPERVISOR_MODEL_NAME", "gpt-5.6-sol")
    get_settings.cache_clear()

    assignment = select_agent_model(
        agent_id=SUPERVISOR_AGENT_ID,
        stage_name="context_evidence_agent",
        call_kind="supervisor_model_policy",
        state={},
    )

    assert assignment["provider"] == "openai"
    assert assignment["model"] == "gpt-5.6-sol"
    assert assignment["selected_by"] == "supervisor_fixed_upper_model"
    assert assignment["cost_calculation"]["formula"]
    assert assignment["cost_calculation"]["total_cost_usd"] == assignment["estimated_cost_usd"]


def test_router_falls_back_to_vllm_when_external_providers_are_disabled(monkeypatch):
    reset_settings(monkeypatch)
    monkeypatch.setenv("MODEL_ROUTER_ENABLE_OPENAI", "false")
    monkeypatch.setenv("MODEL_ROUTER_ENABLE_ANTHROPIC", "false")
    get_settings.cache_clear()

    assignment = select_agent_model(
        agent_id="process_diagnosis_agent",
        stage_name="process_diagnosis_agent",
        call_kind="agent_command",
        state={"business_processes": [{"id": 1, "name": "test"}]},
    )

    assert assignment["provider"] == "vllm"
    assert assignment["model"] == "gemma-4-e4b-it"


def test_router_prefers_stronger_model_for_large_critic_workload(monkeypatch):
    reset_settings(monkeypatch)
    large_evidence = [
        {"label": f"S{i}", "content": "공식자료 기반 근거 " * 400}
        for i in range(40)
    ]
    candidates = [
        {"process_id": i, "candidate_agent_name": f"Agent {i}", "status": "recommended"}
        for i in range(15)
    ]

    assignment = select_agent_model(
        agent_id="evaluation_critic_agent",
        stage_name="llm_critic",
        call_kind="tool_llm_critic",
        state={
            "evidence_items": large_evidence,
            "priority_ranking": {"items": candidates},
            "agent_evaluation": {"items": candidates},
            "compliance_assessment": {"summary": {"enhanced_review_count": 3}},
        },
    )

    assert assignment["provider"] in {"openai", "anthropic"}
    assert assignment["selected_by"] == "supervisor_cost_performance_formula"
    assert assignment["workload_metrics"]["required_quality_score"] >= 0.75


def test_router_can_pick_lower_cost_extra_gpt_for_simple_agent_work(monkeypatch):
    """단순 작업은 추가 등록한 저가 GPT 후보가 품질 하한을 넘으면 선택될 수 있다."""

    reset_settings(monkeypatch)
    monkeypatch.setenv("MODEL_ROUTER_ENABLE_VLLM", "false")
    monkeypatch.setenv("MODEL_ROUTER_ENABLE_ANTHROPIC", "false")
    monkeypatch.setenv(
        "OPENAI_EXTRA_MODEL_PROFILES_JSON",
        json.dumps(
            [
                {
                    "model": "gpt-cheap-mini",
                    "tier": "economy",
                    "quality_score": 0.74,
                    "speed_score": 0.95,
                    "context_window_tokens": 1_050_000,
                    "input_cost_per_million": 0.10,
                    "output_cost_per_million": 0.40,
                }
            ]
        ),
    )
    get_settings.cache_clear()

    assignment = select_agent_model(
        agent_id="context_evidence_agent",
        stage_name="context_evidence_agent",
        call_kind="agent_command",
        state={"business_processes": [{"id": 1, "name": "간단 업무"}]},
    )

    assert assignment["provider"] == "openai"
    assert assignment["model"] == "gpt-cheap-mini"
    assert assignment["tier"] == "economy"
    assert assignment["selected_profile"]["quality_score"] < 0.82
    assert assignment["score_cards"][0]["eligible_for_selection"] is True


def test_router_excludes_too_weak_extra_gpt_for_high_quality_workload(monkeypatch):
    """큰 critic/report급 작업에서는 품질 하한보다 낮은 초저가 후보를 선택하지 않는다."""

    reset_settings(monkeypatch)
    monkeypatch.setenv("MODEL_ROUTER_ENABLE_VLLM", "false")
    monkeypatch.setenv("MODEL_ROUTER_ENABLE_ANTHROPIC", "false")
    monkeypatch.setenv(
        "OPENAI_EXTRA_MODEL_PROFILES_JSON",
        json.dumps(
            [
                {
                    "model": "gpt-too-weak",
                    "tier": "nano",
                    "quality_score": 0.50,
                    "speed_score": 0.99,
                    "context_window_tokens": 1_050_000,
                    "input_cost_per_million": 0.01,
                    "output_cost_per_million": 0.02,
                }
            ]
        ),
    )
    get_settings.cache_clear()

    large_evidence = [
        {"label": f"S{i}", "content": "공식자료 기반 근거 " * 400}
        for i in range(40)
    ]
    candidates = [
        {"process_id": i, "candidate_agent_name": f"Agent {i}", "status": "recommended"}
        for i in range(18)
    ]
    assignment = select_agent_model(
        agent_id="evaluation_critic_agent",
        stage_name="llm_critic",
        call_kind="tool_llm_critic",
        state={
            "evidence_items": large_evidence,
            "priority_ranking": {"items": candidates},
            "agent_evaluation": {"items": candidates},
            "compliance_assessment": {"summary": {"enhanced_review_count": 3}},
        },
    )

    assert assignment["model"] != "gpt-too-weak"
    weak_card = next(card for card in assignment["score_cards"] if card["model"] == "gpt-too-weak")
    assert weak_card["eligible_for_selection"] is False
    assert assignment["workload_metrics"]["required_quality_score"] >= 0.80


def test_supervisor_ignores_extra_gpt_candidates_and_stays_on_sol(monkeypatch):
    """추가 저가 GPT 후보가 있어도 Supervisor는 설정된 상위 모델을 고정 사용한다."""

    reset_settings(monkeypatch)
    monkeypatch.setenv("SUPERVISOR_MODEL_PROVIDER", "openai")
    monkeypatch.setenv("SUPERVISOR_MODEL_NAME", "gpt-5.6-sol")
    monkeypatch.setenv(
        "OPENAI_EXTRA_MODEL_PROFILES_JSON",
        json.dumps(
            [
                {
                    "model": "gpt-cheap-mini",
                    "tier": "economy",
                    "quality_score": 0.74,
                    "speed_score": 0.95,
                    "context_window_tokens": 1_050_000,
                    "input_cost_per_million": 0.10,
                    "output_cost_per_million": 0.40,
                }
            ]
        ),
    )
    get_settings.cache_clear()

    assignment = select_agent_model(
        agent_id=SUPERVISOR_AGENT_ID,
        stage_name="delivery_orchestration_agent",
        call_kind="supervisor_delegation",
        state={"business_processes": [{"id": 1}]},
    )

    assert assignment["model"] == "gpt-5.6-sol"
    assert assignment["selected_by"] == "supervisor_fixed_upper_model"


def test_timeout_escalation_upgrades_fast_model(monkeypatch):
    reset_settings(monkeypatch)

    previous = select_agent_model(
        agent_id="context_evidence_agent",
        stage_name="context_evidence_agent",
        call_kind="agent_command",
        state={"business_processes": [{"id": 1, "name": "test"}]},
    )
    escalated = select_escalation_model(
        agent_id="context_evidence_agent",
        stage_name="context_evidence_agent",
        call_kind="agent_command",
        state={"business_processes": [{"id": 1, "name": "test"}]},
        previous_assignment=previous,
        failure_reason="APITimeoutError: Request timed out.",
    )

    assert escalated["selected_by"] in {"timeout_escalated_model", "timeout_retry_same_upper_model"}
    assert escalated["cost_calculation"]["total_cost_usd"] == escalated["estimated_cost_usd"]
    assert escalated["selected_profile"]["quality_score"] >= previous["selected_profile"]["quality_score"]


def test_model_availability_error_is_retryable() -> None:
    """model-not-found/access 오류는 다른 후보 재시도 대상으로 분류한다."""

    assert is_model_availability_exception(Exception("model_not_found: gpt-5.6-sol"))
    assert is_model_availability_exception(Exception("You do not have access to model gpt-5.6-sol"))
    assert is_model_availability_exception(Exception("404 model does not exist"))
    assert not is_model_availability_exception(Exception("401 invalid API key"))


def test_supervisor_model_access_error_escalates_to_available_alternative(monkeypatch):
    """Supervisor 상위 모델 접근 실패 시 같은 모델 반복 대신 다른 후보로 내려간다."""

    reset_settings(monkeypatch)
    monkeypatch.setenv("MODEL_ROUTER_ENABLE_ANTHROPIC", "false")
    monkeypatch.setenv("SUPERVISOR_MODEL_PROVIDER", "openai")
    monkeypatch.setenv("SUPERVISOR_MODEL_NAME", "gpt-5.6-sol")
    get_settings.cache_clear()

    previous = select_agent_model(
        agent_id=SUPERVISOR_AGENT_ID,
        stage_name="supervisor",
        call_kind="supervisor_model_policy",
        state={},
    )
    escalated = select_escalation_model(
        agent_id=SUPERVISOR_AGENT_ID,
        stage_name="supervisor",
        call_kind="supervisor_delegation",
        state={},
        previous_assignment=previous,
        failure_reason="NotFoundError: model_not_found: gpt-5.6-sol",
    )

    assert previous["model"] == "gpt-5.6-sol"
    assert escalated["model"] != previous["model"]
    assert escalated["selected_by"] == "timeout_escalated_model"
