"""Supervisor LLM timeout 재시도 정책을 검증한다.

`gpt-5.6-sol` 같은 상위 reasoning 모델은 timeout만으로 낮은 모델로 내려가면
Supervisor 품질 정책이 약해진다. 이 테스트는 순수 timeout일 때 retry 예산 안에서
같은 상위 모델을 계속 더 긴 timeout으로 시도하는지 확인한다.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.agents import supervisor_llm
from app.agents.model_router import SUPERVISOR_AGENT_ID, select_agent_model
from app.core.config import get_settings


def reset_settings(monkeypatch) -> None:
    """Supervisor LLM retry 테스트에 필요한 최소 환경변수를 세팅한다."""

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/db")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("SUPERVISOR_MODEL_PROVIDER", "openai")
    monkeypatch.setenv("SUPERVISOR_MODEL_NAME", "gpt-5.6-sol")
    monkeypatch.setenv("SUPERVISOR_LLM_ENABLED", "true")
    monkeypatch.setenv("SUPERVISOR_LLM_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("SUPERVISOR_LLM_RETRY_COUNT", "2")
    monkeypatch.setenv("SUPERVISOR_LLM_RETRY_TIMEOUT_MULTIPLIER", "1.8")
    get_settings.cache_clear()


def test_supervisor_timeout_keeps_same_sol_for_retry_budget(monkeypatch) -> None:
    """Sol timeout이면 Terra로 내려가지 않고 retry 예산 동안 Sol을 계속 재시도한다."""

    reset_settings(monkeypatch)
    model_assignment = select_agent_model(
        agent_id=SUPERVISOR_AGENT_ID,
        stage_name="context_evidence_agent",
        call_kind="supervisor_delegation",
        state={},
    )
    calls: list[dict[str, object]] = []

    def fake_get_chat_model(*, temperature, timeout, model_assignment):
        calls.append(
            {
                "temperature": temperature,
                "timeout": timeout,
                "model": model_assignment.get("model"),
                "selected_by": model_assignment.get("selected_by"),
            }
        )
        return object()

    def fake_invoke_chat_with_retry(llm, messages, retries):
        if len(calls) <= 2:
            raise TimeoutError("Request timed out.")
        return SimpleNamespace(
            content='{"supervisor_intent":"진행","node_order":["retrieve_context"],"route_hint":"continue"}'
        )

    monkeypatch.setattr(supervisor_llm, "get_chat_model", fake_get_chat_model)
    monkeypatch.setattr(supervisor_llm, "invoke_chat_with_retry", fake_invoke_chat_with_retry)

    delegation = supervisor_llm.run_supervisor_delegation_prompt(
        agent_spec={
            "id": "context_evidence_agent",
            "name": "Context Evidence Agent",
            "purpose": "근거 수집",
        },
        stage_name="context_evidence_agent",
        internal_nodes=["retrieve_context"],
        state={"user_request": "AX 후보를 추천해줘"},
        model_assignment=model_assignment,
    )

    assert [call["model"] for call in calls] == ["gpt-5.6-sol", "gpt-5.6-sol", "gpt-5.6-sol"]
    assert [call["selected_by"] for call in calls] == [
        "supervisor_fixed_upper_model",
        "timeout_retry_same_upper_model",
        "timeout_retry_same_upper_model",
    ]
    assert [call["timeout"] for call in calls] == [45.0, 81.0, 145.8]
    assert [item["status"] for item in delegation["retry_attempts"]] == ["timeout", "timeout", "success"]
    assert delegation["model_selection"]["model"] == "gpt-5.6-sol"
    assert delegation["model_selection"]["selected_by"] == "timeout_retry_same_upper_model"
    assert delegation["model_retry_assignments"][0]["selected_by"] == "timeout_retry_same_upper_model"
    assert delegation["model_retry_assignments"][1]["selected_by"] == "timeout_retry_same_upper_model"
