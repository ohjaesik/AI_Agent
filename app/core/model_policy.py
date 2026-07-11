# app/core/model_policy.py
"""LLM 모델 호출, retry, timeout, 접근성 오류 판정에 쓰는 공통 정책.

모델 선택 자체는 `app.agents.model_router`가 담당하지만, 선택된 모델을 호출할 때의
timeout/retry/오류 분류는 Supervisor LLM, Expert Agent LLM, core LLM client가 모두
같은 기준을 써야 한다. 이 모듈은 그 공통 기준을 한 군데에 모아 둔다.
"""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings


MODEL_AVAILABILITY_ERROR_MARKERS = (
    "model_not_found",
    "model not found",
    "model_not_available",
    "does not exist",
    "doesn't exist",
    "do not have access to",
    "does not have access to",
    "not have access to",
    "invalid model",
    "unsupported model",
    "model is not supported",
    "deployment not found",
)

TIMEOUT_ERROR_MARKERS = (
    "timeout",
    "timed out",
    "readtimeout",
)

RETRY_SCOPE_ATTRS = {
    "agent": {
        "timeout": ("agent_llm_timeout_seconds",),
        "retry_count": ("agent_llm_retry_count",),
        "timeout_multiplier": ("agent_llm_retry_timeout_multiplier",),
    },
    "supervisor": {
        "timeout": ("supervisor_llm_timeout_seconds", "agent_llm_timeout_seconds"),
        "retry_count": ("supervisor_llm_retry_count",),
        "timeout_multiplier": ("supervisor_llm_retry_timeout_multiplier",),
    },
}


def normalize_blank(value: str | None, default: str) -> str:
    """빈 문자열/None을 설정 기본값으로 대체한다."""

    if value is None:
        return default

    value = str(value).strip()
    return value if value else default


def _safe_settings_value(attr_names: tuple[str, ...], default: Any) -> Any:
    """환경 설정 접근 실패가 LLM fallback 경로까지 막지 않도록 안전하게 읽는다."""

    try:
        settings = get_settings()
        for attr_name in attr_names:
            value = getattr(settings, attr_name, None)
            if value not in (None, ""):
                return value
    except Exception:
        return default
    return default


def _attrs_for_scope(scope: str, field: str) -> tuple[str, ...]:
    """agent/supervisor scope에 맞는 Settings attribute 목록을 반환한다."""

    return RETRY_SCOPE_ATTRS.get(scope, RETRY_SCOPE_ATTRS["agent"])[field]


def safe_model_timeout(scope: str, default: float) -> float:
    """scope별 LLM timeout 설정을 안전하게 float로 읽는다."""

    try:
        return float(_safe_settings_value(_attrs_for_scope(scope, "timeout"), default) or default)
    except (TypeError, ValueError):
        return default


def safe_model_retry_count(scope: str, default: int) -> int:
    """scope별 LLM retry 횟수를 0 이상의 정수로 읽는다."""

    try:
        return max(0, int(_safe_settings_value(_attrs_for_scope(scope, "retry_count"), default) or default))
    except (TypeError, ValueError):
        return default


def safe_model_retry_timeout_multiplier(scope: str, default: float) -> float:
    """retry마다 timeout을 늘리는 배수를 1.0 이상으로 읽는다."""

    try:
        return max(1.0, float(_safe_settings_value(_attrs_for_scope(scope, "timeout_multiplier"), default) or default))
    except (TypeError, ValueError):
        return default


def retry_timeout_seconds(base_timeout: float, timeout_multiplier: float, attempt_index: int) -> float:
    """n번째 retry attempt에 적용할 timeout을 계산한다."""

    return round(float(base_timeout) * (float(timeout_multiplier) ** max(0, attempt_index - 1)), 3)


def is_timeout_exception(exc: Exception) -> bool:
    """Provider별 timeout 예외 이름이 달라 문자열 marker로 timeout을 감지한다."""

    text = f"{type(exc).__name__}: {exc}".lower()
    return any(marker in text for marker in TIMEOUT_ERROR_MARKERS)


def is_model_availability_exception(exc: Exception) -> bool:
    """모델명 없음/접근권한 없음처럼 다른 모델로 재시도 가능한 오류인지 판단한다."""

    text = f"{type(exc).__name__}: {exc}".lower()
    if any(marker in text for marker in MODEL_AVAILABILITY_ERROR_MARKERS):
        return True
    return "404" in text and "model" in text


def retry_status_for_exception(exc: Exception) -> str:
    """retry trace에 남길 표준 상태값을 반환한다."""

    if is_timeout_exception(exc):
        return "timeout"
    if is_model_availability_exception(exc):
        return "model_unavailable"
    return "failed"


def is_retryable_llm_exception(exc: Exception) -> bool:
    """timeout 또는 모델 접근성 문제처럼 재시도할 가치가 있는 오류인지 판단한다."""

    return is_timeout_exception(exc) or is_model_availability_exception(exc)


def should_retry_same_upper_model_on_timeout(
    *,
    timed_out: bool,
    model_unavailable: bool,
    attempt_model_assignment: dict[str, Any] | None,
    original_model_assignment: dict[str, Any] | None,
) -> bool:
    """Supervisor 상위 모델 timeout이면 같은 모델을 재시도할지 판단한다."""

    return (
        timed_out
        and not model_unavailable
        and bool(attempt_model_assignment)
        and (attempt_model_assignment or {}).get("provider") == (original_model_assignment or {}).get("provider")
        and (attempt_model_assignment or {}).get("model") == (original_model_assignment or {}).get("model")
    )


def build_same_upper_model_retry_assignment(
    model_assignment: dict[str, Any] | None,
    *,
    failure_reason: str,
) -> dict[str, Any] | None:
    """Supervisor 상위 모델 timeout 시 같은 모델을 더 긴 timeout으로 재시도하게 표시한다."""

    if not model_assignment:
        return None

    retry_assignment = dict(model_assignment)
    retry_assignment["selected_by"] = "timeout_retry_same_upper_model"
    retry_assignment["reason"] = (
        "Supervisor 상위 모델이 timeout되어 같은 모델을 더 긴 timeout으로 재시도한다. "
        f"실패 원인: {failure_reason}"
    )
    return retry_assignment
