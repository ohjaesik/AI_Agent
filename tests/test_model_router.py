from __future__ import annotations

from app.agents.model_router import SUPERVISOR_AGENT_ID, select_agent_model
from app.core.config import get_settings


def reset_settings(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/db")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("VLLM_MODEL", "gemma-4-e4b-it")
    get_settings.cache_clear()


def test_supervisor_uses_configured_upper_model(monkeypatch):
    reset_settings(monkeypatch)
    monkeypatch.setenv("SUPERVISOR_MODEL_PROVIDER", "openai")
    monkeypatch.setenv("SUPERVISOR_MODEL_NAME", "gpt-4.1")
    get_settings.cache_clear()

    assignment = select_agent_model(
        agent_id=SUPERVISOR_AGENT_ID,
        stage_name="context_evidence_agent",
        call_kind="supervisor_model_policy",
        state={},
    )

    assert assignment["provider"] == "openai"
    assert assignment["model"] == "gpt-4.1"
    assert assignment["selected_by"] == "supervisor_fixed_upper_model"


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

