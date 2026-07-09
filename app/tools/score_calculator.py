# app/tools/score_calculator.py

from __future__ import annotations

from typing import Any


DISCOVERY_BONUS_MAX = 0.35


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


def calculate_priority_score(expected_effect: int, data_accessibility: int, repeatability: int, feasibility: int, user_acceptance: int, risk_score: int, implementation_cost_score: int) -> float:
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


def calculate_discovery_bonus(discovery_metadata: dict[str, Any] | None) -> float:
    if not discovery_metadata:
        return 0.0
    bonus = 0.0
    if discovery_metadata.get("discovery_mode") == "llm_company_process_discovery":
        bonus += 0.12
    evidence_labels = discovery_metadata.get("evidence_labels") or []
    if evidence_labels:
        bonus += min(len(evidence_labels), 3) * 0.04
    if str(discovery_metadata.get("suitability_rationale") or "").strip():
        bonus += 0.08
    score_rationale = discovery_metadata.get("score_rationale") or {}
    if isinstance(score_rationale, dict):
        meaningful_rationales = [value for value in score_rationale.values() if str(value).strip()]
        if len(meaningful_rationales) >= 3:
            bonus += 0.07
    if discovery_metadata.get("discovery_mode") == "template_fallback":
        bonus -= 0.08
    return round(max(0.0, min(bonus, DISCOVERY_BONUS_MAX)), 2)


def build_compliance_map(compliance_assessment: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for item in (compliance_assessment or {}).get("items", []):
        process_id = safe_int(item.get("process_id"), 0)
        if process_id:
            result[process_id] = item
    return result


def apply_compliance_status(base_status: str, compliance_item: dict[str, Any] | None) -> str:
    if not compliance_item:
        return base_status
    if compliance_item.get("blocked"):
        return "excluded"
    compliance_level = compliance_item.get("compliance_level")
    if compliance_item.get("human_review_required") or compliance_level in {"enhanced_review", "sensitive_review"}:
        if base_status == "recommended":
            return "human_review_required"
    return base_status


def determine_candidate_status(risk_score: int, data_accessibility: int, saving_rate: float, risk_flags: list[str] | None = None) -> str:
    risk_flags = risk_flags or []
    if "excluded_from_mvp" in risk_flags:
        return "excluded"
    if risk_score >= 5:
        return "excluded"
    if risk_score >= 4:
        return "human_review_required"
    if "social_impact_review_required" in risk_flags:
        return "human_review_required"
    if data_accessibility <= 2:
        return "data_preparation_required"
    if saving_rate < 20:
        return "low_roi"
    return "recommended"


def build_compliance_reason(compliance_item: dict[str, Any] | None) -> str:
    if not compliance_item:
        return ""
    parts = []
    if compliance_item.get("blocked"):
        parts.append("규제 스크리닝에서 금지 또는 부적절 사용 가능성이 탐지되어 MVP 후보에서 제외한다.")
    if compliance_item.get("high_impact_categories"):
        parts.append(f"고영향 가능성 분류: {', '.join(compliance_item.get('high_impact_categories', []))}.")
    if compliance_item.get("sensitive_hits"):
        parts.append(f"민감정보/기밀 관련 신호: {', '.join(compliance_item.get('sensitive_hits', []))}.")
    if compliance_item.get("required_controls"):
        parts.append(f"필수 통제: {', '.join(compliance_item.get('required_controls', []))}.")
    return " ".join(parts)


def build_esg_social_reason(risk_flags: list[str]) -> str:
    if "social_impact_review_required" not in risk_flags:
        return ""
    controls = []
    if "workforce_transition_required" in risk_flags:
        controls.append("인력 대체·직무 전환 영향 검토")
    if "employee_monitoring_guardrail_required" in risk_flags:
        controls.append("직원 모니터링 목적 제한 및 개인 단위 징계 활용 금지")
    if "reskilling_plan_required" in risk_flags:
        controls.append("재교육·역량 전환 계획")
    if "labor_stakeholder_review_required" in risk_flags:
        controls.append("현장·노사 수용성 검토")
    if "accessibility_fallback_required" in risk_flags:
        controls.append("사람 상담/비디지털 접근 경로 유지")
    if controls:
        return f"ESG Social 영향 검토 필요: {', '.join(controls)}."
    return "ESG Social 영향 검토 필요: Agent 도입에 따른 이해관계자 영향과 수용성을 Human Review에서 확인해야 한다."


def build_status_reason(status: str, risk_score: int, data_accessibility: int, saving_rate: float, risk_flags: list[str] | None = None, discovery_metadata: dict[str, Any] | None = None, discovery_bonus: float = 0.0, compliance_item: dict[str, Any] | None = None) -> str:
    risk_flags = risk_flags or []
    discovery_metadata = discovery_metadata or {}
    suitability_rationale = str(discovery_metadata.get("suitability_rationale") or "").strip()

    if status == "excluded":
        base_reason = "위험도가 매우 높거나 MVP 범위에서 제외해야 하는 업무이다."
    elif status == "human_review_required":
        base_reason = "위험도, 규제 스크리닝 또는 ESG Social 영향도상 Human Review 후 PoC 착수 여부를 결정해야 한다."
    elif status == "data_preparation_required":
        base_reason = "데이터 접근성이 낮아 데이터 정비와 접근권한 확인을 선행해야 한다."
    elif status == "low_roi":
        base_reason = "예상 절감률이 낮아 우선순위에서 후순위로 배치한다."
    elif risk_flags and risk_flags != ["standard_review"]:
        base_reason = "추천 가능하지만 보안·거버넌스 통제 조건을 함께 적용해야 한다."
    else:
        base_reason = "기대효과, 데이터 접근성, 구현 가능성, 위험도를 종합했을 때 PoC 후보로 적합하다."

    esg_social_reason = build_esg_social_reason(risk_flags)
    if esg_social_reason:
        base_reason = f"{base_reason} {esg_social_reason}"

    compliance_reason = build_compliance_reason(compliance_item)
    if compliance_reason:
        base_reason = f"{base_reason} Compliance 근거: {compliance_reason}"
    if suitability_rationale:
        return f"{base_reason} Discovery 근거: {suitability_rationale} Discovery bonus={discovery_bonus}."
    return base_reason


def build_roi_map(roi_cost: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for item in (roi_cost or {}).get("items", []):
        process_id = safe_int(item.get("process_id"), 0)
        if process_id:
            result[process_id] = item
    return result


def build_risk_map(risk_governance: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for item in (risk_governance or {}).get("items", []):
        process_id = safe_int(item.get("process_id"), 0)
        if process_id:
            result[process_id] = item
    return result


def rank_agent_candidates(processes: list[dict[str, Any]], roi_cost: dict[str, Any] | None = None, risk_governance: dict[str, Any] | None = None, compliance_assessment: dict[str, Any] | None = None) -> dict[str, Any]:
    roi_map = build_roi_map(roi_cost)
    risk_map = build_risk_map(risk_governance)
    effective_compliance = compliance_assessment or (risk_governance or {}).get("compliance_assessment")
    compliance_map = build_compliance_map(effective_compliance)

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
        discovery_metadata = process.get("discovery_metadata") or {}

        base_score = calculate_priority_score(expected_effect, data_accessibility, repeatability, feasibility, user_acceptance, risk_score, implementation_cost_score)
        discovery_bonus = calculate_discovery_bonus(discovery_metadata)
        final_score = round(base_score + discovery_bonus, 2)

        roi_item = roi_map.get(process_id, {})
        risk_item = risk_map.get(process_id, {})
        compliance_item = compliance_map.get(process_id, {})
        saving_rate = safe_float(roi_item.get("saving_rate"), 0.0)
        risk_flags = risk_item.get("flags", [])

        status = determine_candidate_status(risk_score, data_accessibility, saving_rate, risk_flags)
        status = apply_compliance_status(status, compliance_item)
        reason = build_status_reason(status, risk_score, data_accessibility, saving_rate, risk_flags, discovery_metadata, discovery_bonus, compliance_item)

        candidates.append({
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
            "base_score": base_score,
            "discovery_bonus": discovery_bonus,
            "final_score": final_score,
            "saving_rate": saving_rate,
            "monthly_saving": safe_int(roi_item.get("monthly_saving"), 0),
            "risk_flags": risk_flags,
            "esg_social_risks": risk_item.get("esg_social_risks", []),
            "esg_social_controls": risk_item.get("esg_social_controls", []),
            "status": status,
            "reason": reason,
            "discovery_metadata": discovery_metadata,
            "score_rationale": discovery_metadata.get("score_rationale", {}) if isinstance(discovery_metadata, dict) else {},
            "suitability_rationale": discovery_metadata.get("suitability_rationale") if isinstance(discovery_metadata, dict) else None,
            "compliance": compliance_item,
        })

    candidates.sort(key=lambda item: (item["status"] == "recommended", item["status"] == "human_review_required", item["final_score"], item["saving_rate"]), reverse=True)
    for rank, candidate in enumerate(candidates, start=1):
        candidate["rank"] = rank

    recommended = [item for item in candidates if item["status"] == "recommended"]
    review_required = [item for item in candidates if item["status"] == "human_review_required"]
    excluded = [item for item in candidates if item["status"] == "excluded"]
    social_impact_review = [item for item in candidates if "social_impact_review_required" in item.get("risk_flags", [])]

    return {
        "items": candidates,
        "summary": {
            "total_candidates": len(candidates),
            "recommended_count": len(recommended),
            "review_required_count": len(review_required),
            "excluded_count": len(excluded),
            "social_impact_review_count": len(social_impact_review),
            "top_candidate": candidates[0] if candidates else None,
            "compliance_overall_status": (effective_compliance or {}).get("overall_status"),
            "compliance_summary": (effective_compliance or {}).get("summary", {}),
        },
    }
