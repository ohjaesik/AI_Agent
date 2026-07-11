"""Agent 모델 선택 기록을 최종 비용 요약으로 집계한다.

`agent_model_decisions`에는 Supervisor/Expert Agent가 어떤 모델을 골랐는지와
예상 비용이 호출 단위로 누적된다. 이 모듈은 그 세부 trace를 UI/API가 바로 볼 수
있는 top-level `total_cost_summary` 형태로 변환한다.
"""

from __future__ import annotations

import json
from typing import Any


def _as_float(value: Any, default: float = 0.0) -> float:
    """숫자/문자열 비용 값을 안전하게 float로 변환한다."""

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    """token 수처럼 정수로 합산할 값을 안전하게 int로 변환한다."""

    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _decision_marker(decision: dict[str, Any]) -> str:
    """같은 model decision이 여러 경로로 합쳐져도 한 번만 세기 위한 marker를 만든다."""

    explicit_id = decision.get("decision_id")
    if explicit_id:
        return str(explicit_id)
    try:
        return json.dumps(decision, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        return str(decision)


def _decision_cost(decision: dict[str, Any]) -> float:
    """model decision에서 예상 비용을 읽는다.

    최신 router는 `estimated_cost_usd`를 직접 넣고, 세부 산식은
    `cost_calculation.total_cost_usd`에 함께 남긴다. 둘 중 직접 비용이 없으면
    세부 산식 값을 fallback으로 사용한다.
    """

    if decision.get("estimated_cost_usd") is not None:
        return _as_float(decision.get("estimated_cost_usd"))
    return _as_float((decision.get("cost_calculation") or {}).get("total_cost_usd"))


def _rollup_item() -> dict[str, Any]:
    """provider/model/call_kind별 집계 bucket의 기본 구조를 만든다."""

    return {
        "decision_count": 0,
        "estimated_cost_usd": 0.0,
        "estimated_input_tokens": 0,
        "estimated_output_tokens": 0,
    }


def _add_rollup(bucket: dict[str, dict[str, Any]], key: str, decision: dict[str, Any], cost: float) -> None:
    """한 decision을 지정된 집계 bucket에 더한다."""

    item = bucket.setdefault(key, _rollup_item())
    cost_calculation = decision.get("cost_calculation") or {}
    item["decision_count"] += 1
    item["estimated_cost_usd"] += cost
    item["estimated_input_tokens"] += _as_int(cost_calculation.get("estimated_input_tokens"))
    item["estimated_output_tokens"] += _as_int(cost_calculation.get("estimated_output_tokens"))


def _finalize_rollup(bucket: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """집계 결과를 JSON으로 보기 좋게 정렬하고 비용 소수점을 정리한다."""

    finalized: dict[str, dict[str, Any]] = {}
    for key in sorted(bucket):
        item = dict(bucket[key])
        item["estimated_cost_usd"] = round(float(item["estimated_cost_usd"]), 6)
        finalized[key] = item
    return finalized


def build_total_cost_summary(model_decisions: list[dict[str, Any]] | None) -> dict[str, Any]:
    """`agent_model_decisions` 전체를 top-level 비용 요약으로 집계한다.

    반환값은 실제 청구액이 아니라 router가 호출 전 workload/token 추정치로 계산한
    예상 비용이다. 그래도 모든 호출의 provider/model/call_kind별 비용 추세를 빠르게
    볼 수 있어 실행 검증과 UI 표시에는 충분히 유용하다.
    """

    decisions = [item for item in (model_decisions or []) if isinstance(item, dict)]
    seen: set[str] = set()
    unique_decisions: list[dict[str, Any]] = []

    for decision in decisions:
        marker = _decision_marker(decision)
        if marker in seen:
            continue
        seen.add(marker)
        unique_decisions.append(decision)

    by_provider: dict[str, dict[str, Any]] = {}
    by_model: dict[str, dict[str, Any]] = {}
    by_call_kind: dict[str, dict[str, Any]] = {}
    total_cost = 0.0
    priced_count = 0

    for decision in unique_decisions:
        cost = _decision_cost(decision)
        if cost > 0:
            priced_count += 1
        total_cost += cost

        provider = str(decision.get("provider") or "unknown")
        model = str(decision.get("model") or "unknown")
        call_kind = str(decision.get("call_kind") or "unknown")

        _add_rollup(by_provider, provider, decision, cost)
        _add_rollup(by_model, f"{provider}:{model}", decision, cost)
        _add_rollup(by_call_kind, call_kind, decision, cost)

    return {
        "currency": "USD",
        "estimated_total_cost_usd": round(total_cost, 6),
        "decision_count": len(unique_decisions),
        "priced_decision_count": priced_count,
        "unpriced_decision_count": len(unique_decisions) - priced_count,
        "formula": "sum(unique agent_model_decisions[].estimated_cost_usd or cost_calculation.total_cost_usd)",
        "by_provider": _finalize_rollup(by_provider),
        "by_model": _finalize_rollup(by_model),
        "by_call_kind": _finalize_rollup(by_call_kind),
    }
