# app/tools/cost_calculator.py

"""업무별 ROI/비용 절감 추정 tool.

현재 투입 시간, 반복 빈도, 자동화 보조율, PoC 비용 가정을 기반으로 baseline cost와
절감률을 계산한다.
"""

from __future__ import annotations

from typing import Any


def clamp(value: float, minimum: float, maximum: float) -> float:
    """점수나 비율이 허용 범위를 벗어나지 않도록 제한한다."""
    return max(minimum, min(value, maximum))


def safe_float(value: Any, default: float = 0.0) -> float:
    """None/문자열/잘못된 값을 안전하게 실수로 변환한다."""
    if value is None:
        return default

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    """None/문자열/잘못된 값을 안전하게 정수로 변환한다."""
    if value is None:
        return default

    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def estimate_time_reduction_rate(process: dict[str, Any]) -> float:
    """
    Automation Feasibility Agent가 아직 없을 때 사용하는 deterministic fallback.

    expected_effect, repeatability, tech_feasibility가 높을수록 절감률을 높게 보고,
    risk_score가 높으면 실제 적용 가능성이 낮으므로 절감률을 낮춘다.

    반환값은 0.10~0.70 사이 float.
    """
    expected_effect = safe_int(process.get("expected_effect"), 3)
    repeatability = safe_int(process.get("repeatability"), 3)
    tech_feasibility = safe_int(process.get("tech_feasibility"), 3)
    risk_score = safe_int(process.get("risk_score"), 3)

    reduction_rate = (
        expected_effect * 0.08
        + repeatability * 0.04
        + tech_feasibility * 0.04
        - risk_score * 0.03
    )

    return round(clamp(reduction_rate, 0.10, 0.70), 2)


def calculate_process_roi(
    process: dict[str, Any],
    expected_time_reduction_rate: float | None = None,
) -> dict[str, Any]:
    """
    업무 1개에 대한 월간 비용 절감 효과를 계산한다.

    monthly_current_cost = weekly_hours × hourly_cost × 4
    monthly_expected_cost = monthly_current_cost × (1 - expected_time_reduction_rate)
    saving = monthly_current_cost - monthly_expected_cost
    saving_rate = saving / monthly_current_cost × 100
    """
    process_id = safe_int(process.get("id"))
    weekly_hours = safe_float(process.get("weekly_hours"))
    hourly_cost = safe_int(process.get("hourly_cost"))

    if expected_time_reduction_rate is None:
        expected_time_reduction_rate = estimate_time_reduction_rate(process)

    expected_time_reduction_rate = clamp(expected_time_reduction_rate, 0.0, 1.0)

    monthly_current_cost = weekly_hours * hourly_cost * 4
    monthly_expected_cost = monthly_current_cost * (1 - expected_time_reduction_rate)
    saving = monthly_current_cost - monthly_expected_cost

    saving_rate = 0.0
    if monthly_current_cost > 0:
        saving_rate = saving / monthly_current_cost * 100

    return {
        "process_id": process_id,
        "process_name": process.get("name"),
        "candidate_agent_name": process.get("candidate_agent_name"),
        "weekly_hours": weekly_hours,
        "hourly_cost": hourly_cost,
        "expected_time_reduction_rate": round(expected_time_reduction_rate, 2),
        "monthly_current_cost": int(monthly_current_cost),
        "monthly_expected_cost": int(monthly_expected_cost),
        "monthly_saving": int(saving),
        "saving_rate": round(saving_rate, 1),
        "assumption": (
            "Automation Feasibility Agent 결과가 없을 경우 "
            "expected_effect, repeatability, tech_feasibility, risk_score 기반으로 절감률을 추정한다."
        ),
    }


def calculate_roi_for_processes(
    processes: list[dict[str, Any]],
    automation_feasibility: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    업무 목록 전체에 대한 ROI 계산.

    automation_feasibility가 들어오면 expected_time_reduction_rate를 우선 사용한다.
    없으면 seed 데이터 기반 heuristic fallback을 사용한다.
    """
    feasibility_map: dict[int, float] = {}

    if automation_feasibility:
        for item in automation_feasibility.get("items", []):
            process_id = safe_int(item.get("process_id"))
            rate = item.get("expected_time_reduction_rate")

            if process_id and rate is not None:
                feasibility_map[process_id] = safe_float(rate)

    items: list[dict[str, Any]] = []

    for process in processes:
        process_id = safe_int(process.get("id"))
        expected_rate = feasibility_map.get(process_id)

        items.append(
            calculate_process_roi(
                process=process,
                expected_time_reduction_rate=expected_rate,
            )
        )

    total_current_cost = sum(item["monthly_current_cost"] for item in items)
    total_expected_cost = sum(item["monthly_expected_cost"] for item in items)
    total_saving = total_current_cost - total_expected_cost

    total_saving_rate = 0.0
    if total_current_cost > 0:
        total_saving_rate = total_saving / total_current_cost * 100

    return {
        "items": items,
        "summary": {
            "total_current_cost": int(total_current_cost),
            "total_expected_cost": int(total_expected_cost),
            "total_saving": int(total_saving),
            "total_saving_rate": round(total_saving_rate, 1),
        },
    }