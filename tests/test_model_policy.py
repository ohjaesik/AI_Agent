"""LLM timeout/retry/model availability 공통 정책을 검증한다."""

from app.core.config import get_settings
from app.core.model_policy import (
    build_same_upper_model_retry_assignment,
    is_model_availability_exception,
    is_retryable_llm_exception,
    is_timeout_exception,
    retry_status_for_exception,
    retry_timeout_seconds,
    safe_model_retry_count,
    safe_model_retry_timeout_multiplier,
    safe_model_timeout,
    should_retry_same_upper_model_on_timeout,
)


def reset_settings(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/db")
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("AGENT_LLM_TIMEOUT_SECONDS", "10")
    monkeypatch.setenv("AGENT_LLM_RETRY_COUNT", "1")
    monkeypatch.setenv("AGENT_LLM_RETRY_TIMEOUT_MULTIPLIER", "1.6")
    monkeypatch.setenv("SUPERVISOR_LLM_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("SUPERVISOR_LLM_RETRY_COUNT", "2")
    monkeypatch.setenv("SUPERVISOR_LLM_RETRY_TIMEOUT_MULTIPLIER", "1.8")
    get_settings.cache_clear()


def test_model_policy_reads_agent_and_supervisor_retry_settings(monkeypatch) -> None:
    reset_settings(monkeypatch)

    assert safe_model_timeout("agent", default=8.0) == 10.0
    assert safe_model_retry_count("agent", default=0) == 1
    assert safe_model_retry_timeout_multiplier("agent", default=1.0) == 1.6
    assert safe_model_timeout("supervisor", default=8.0) == 45.0
    assert safe_model_retry_count("supervisor", default=0) == 2
    assert safe_model_retry_timeout_multiplier("supervisor", default=1.0) == 1.8


def test_model_policy_classifies_retryable_errors() -> None:
    timeout_error = TimeoutError("Request timed out.")
    model_error = Exception("model_not_found: gpt-5.6-sol")
    auth_error = Exception("401 invalid API key")

    assert is_timeout_exception(timeout_error)
    assert is_model_availability_exception(model_error)
    assert retry_status_for_exception(timeout_error) == "timeout"
    assert retry_status_for_exception(model_error) == "model_unavailable"
    assert retry_status_for_exception(auth_error) == "failed"
    assert is_retryable_llm_exception(timeout_error)
    assert is_retryable_llm_exception(model_error)
    assert not is_retryable_llm_exception(auth_error)


def test_model_policy_calculates_retry_timeout_sequence() -> None:
    assert retry_timeout_seconds(45.0, 1.8, 1) == 45.0
    assert retry_timeout_seconds(45.0, 1.8, 2) == 81.0
    assert retry_timeout_seconds(45.0, 1.8, 3) == 145.8


def test_supervisor_same_upper_model_retry_assignment() -> None:
    assignment = {
        "provider": "openai",
        "model": "gpt-5.6-sol",
        "selected_by": "supervisor_fixed_upper_model",
    }

    assert should_retry_same_upper_model_on_timeout(
        timed_out=True,
        model_unavailable=False,
        attempt_model_assignment=assignment,
        original_model_assignment=assignment,
    )
    retry_assignment = build_same_upper_model_retry_assignment(
        assignment,
        failure_reason="TimeoutError: Request timed out.",
    )

    assert retry_assignment["model"] == "gpt-5.6-sol"
    assert retry_assignment["selected_by"] == "timeout_retry_same_upper_model"
