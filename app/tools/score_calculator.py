# app/tools/score_calculator.py

from __future__ import annotations

from typing import Any


def safe_int(value: Any, default: int = 3) -> int:
    if value is None:
        return default

    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def clamp_score(value: int) -> int:
    return max(1, min(value, 5))


def calculate_priority_score(
    expected_effect: int,
    data_accessibility: int,
    repeatability: int,
    feasibility: int,
    user_acceptance: int,
    risk_score: int,
    implementation_cost_score: int,
) -> float:
    """
    최종 AX 우선순위 점수 =
    (기대효과 × 0.35)
    + (데이터 접근성 × 0.20)
    + (반복성 × 0.15)
    + (구현 용이성 × 0.15)
    + (현업 수용성 × 0.10)
    - (보안/거버넌스 위험 × 0.15)
    - (추정 구현 비용 × 0.10)
    """
    score = (
        clamp_score(expected_effect) * 0.35
        + clamp_score(data_accessibility) * 0.20
        + clamp_score(repeatability) * 0.15
        + clamp_score(feasibility) * 0.15
        + clamp_score(user_acceptance) * 0.10
        - clamp_score(risk_score) * 0.15
        - clamp_score(implementation_cost_score) * 0.10
    )

    return round(score, 2)


def determine_candidate_status(
    risk_score: int,
    data_accessibility: int,
    saving_rate: float,
    risk_flags: list[str] | None = None,
) -> str:
    risk_flags = risk_flags or []

    if "excluded_from_mvp" in risk_flags:
        return "excluded"

    if risk_score >= 5:
        return "excluded"

    if risk_score >= 4:
        return "human_review_required"

    if data_accessibility <= 2:
        return "data_preparation_required"

    if saving_rate < 20:
        return "low_roi"

    return "recommended"


def build_status_reason(
    status: str,
    risk_score: int,
    data_accessibility: int,
    saving_rate: float,
    risk_flags: list[str] | None = None,
) -> str:
    risk_flags = risk_flags or []

    if status == "excluded":
        return "위험도가 매우 높거나 MVP 범위에서 제외해야 하는 업무이다."

    if status == "human_review_required":
        return "위험도 4 이상 업무이므로 Human Review 후 PoC 착수 여부를 결정해야 한다."

    if status == "data_preparation_required":
        return "데이터 접근성이 낮아 데이터 정비와 접근권한 확인을 선행해야 한다."

    if status == "low_roi":
        return "예상 절감률이 낮아 우선순위에서 후순위로 배치한다."

    if risk_flags and risk_flags != ["standard_review"]:
        return "추천 가능하지만 보안·거버넌스 통제 조건을 함께 적용해야 한다."

    return "기대효과, 데이터 접근성, 구현 가능성, 위험도를 종합했을 때 PoC 후보로 적합하다."


def build_roi_map(roi_cost: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    if not roi_cost:
        return {}

    result: dict[int, dict[str, Any]] = {}

    for item in roi_cost.get("items", []):
        process_id = safe_int(item.get("process_id"), 0)
        if process_id:
            result[process_id] = item

    return result


def build_risk_map(risk_governance: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    if not risk_governance:
        return {}

    result: dict[int, dict[str, Any]] = {}

    for item in risk_governance.get("items", []):
        process_id = safe_int(item.get("process_id"), 0)
        if process_id:
            result[process_id] = item

    return result


def rank_agent_candidates(
    processes: list[dict[str, Any]],
    roi_cost: dict[str, Any] | None = None,
    risk_governance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    roi_map = build_roi_map(roi_cost)
    risk_map = build_risk_map(risk_governance)

    candidates: list[dict[str, Any]] = []

    for process in processes:
        process_id = safe_int(process.get("id"), 0)

        expected_effect = safe_int(process.get("expected_effect"), 3)
        data_accessibility = safe_int(process.get("data_accessibility"), 3)
        repeatability = safe_int(process.get("repeatability"), 3)
        feasibility = safe_int(process.get("tech_feasibility"), 3)
        user_acceptance = safe_int(process.get("user_acceptance"), 3)
        risk_score = safe_int(process.get("risk_score"), 3)
        implementation_cost_score = safe_int(process.get("implementation_cost_score"), 3)

        final_score = calculate_priority_score(
            expected_effect=expected_effect,
            data_accessibility=data_accessibility,
            repeatability=repeatability,
            feasibility=feasibility,
            user_acceptance=user_acceptance,
            risk_score=risk_score,
            implementation_cost_score=implementation_cost_score,
        )

        roi_item = roi_map.get(process_id, {})
        risk_item = risk_map.get(process_id, {})

        saving_rate = safe_float(roi_item.get("saving_rate"), 0.0)
        risk_flags = risk_item.get("flags", [])

        status = determine_candidate_status(
            risk_score=risk_score,
            data_accessibility=data_accessibility,
            saving_rate=saving_rate,
            risk_flags=risk_flags,
        )

        reason = build_status_reason(
            status=status,
            risk_score=risk_score,
            data_accessibility=data_accessibility,
            saving_rate=saving_rate,
            risk_flags=risk_flags,
        )

        candidates.append(
            {
                "process_id": process_id,
                "process_name": process.get("name"),
                "candidate_agent_name": process.get("candidate_agent_name"),
                "target_user": process.get("target_user"),
                "problem": process.get("problem"),
                "expected_effect": expected_effect,
                "data_accessibility": data_accessibility,
                "repeatability": repeatability,
                "feasibility": feasibility,
                "user_acceptance": user_acceptance,
                "risk_score": risk_score,
                "implementation_cost_score": implementation_cost_score,
                "final_score": final_score,
                "saving_rate": saving_rate,
                "monthly_saving": safe_int(roi_item.get("monthly_saving"), 0),
                "risk_flags": risk_flags,
                "status": status,
                "reason": reason,
            }
        )

    candidates.sort(
        key=lambda item: (
            item["status"] == "recommended",
            item["final_score"],
            item["saving_rate"],
        ),
        reverse=True,
    )

    for rank, candidate in enumerate(candidates, start=1):
        candidate["rank"] = rank

    recommended = [item for item in candidates if item["status"] == "recommended"]
    review_required = [
        item for item in candidates if item["status"] == "human_review_required"
    ]
    excluded = [item for item in candidates if item["status"] == "excluded"]

    return {
        "items": candidates,
        "summary": {
            "total_candidates": len(candidates),
            "recommended_count": len(recommended),
            "review_required_count": len(review_required),
            "excluded_count": len(excluded),
            "top_candidate": candidates[0] if candidates else None,
        },
    }