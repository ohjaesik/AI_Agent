# app/tools/score_calculator.py

"""후보 업무의 PoC 우선순위 점수를 계산한다.

효과, 반복성, 문서 의존도, 데이터 준비도, 기술 가능성, 리스크, ROI를 조합해 ranking을
만든다.
"""

from __future__ import annotations

from typing import Any


DISCOVERY_BONUS_MAX = 0.35


def safe_int(value: Any, default: int = 3) -> int:
    """None/문자열/잘못된 값을 안전하게 정수로 변환한다."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    """None/문자열/잘못된 값을 안전하게 실수로 변환한다."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def clamp_score(value: int) -> int:
    """업무 평가 점수를 1-5 범위로 제한한다."""
    return max(1, min(value, 5))


def calculate_priority_score(expected_effect: int, data_accessibility: int, repeatability: int, feasibility: int, user_acceptance: int, risk_score: int, implementation_cost_score: int) -> float:
    """후보의 효과/반복성/readiness/ROI/risk 점수를 하나의 우선순위 점수로 합산한다."""
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
    """공식자료 기반 LLM discovery와 evidence/rationale 충실도에 따른 가산점을 계산한다."""
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
    """compliance assessment 결과를 ranking 계산 중 process_id로 찾아볼 수 있게 만든다."""
    result: dict[int, dict[str, Any]] = {}
    for item in (compliance_assessment or {}).get("items", []):
        process_id = safe_int(item.get("process_id"), 0)
        if process_id:
            result[process_id] = item
    return result


def apply_compliance_status(base_status: str, compliance_item: dict[str, Any] | None) -> str:
    """규제상 blocked/review 필요 신호가 있으면 ranking status를 보수적으로 조정한다."""
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
    """risk, 데이터 준비도, 절감률을 기준으로 후보의 기본 추천 상태를 결정한다."""
    risk_flags = risk_flags or []
    if "excluded_from_mvp" in risk_flags:
        return "excluded"
    if risk_score >= 5:
        return "excluded"
    if risk_score >= 4:
        return "human_review_required"
    if "esg_review_required" in risk_flags:
        return "human_review_required"
    if data_accessibility <= 2:
        return "data_preparation_required"
    if saving_rate < 20:
        return "low_roi"
    return "recommended"


def build_compliance_reason(compliance_item: dict[str, Any] | None) -> str:
    """compliance status가 ranking reason에 반영될 수 있도록 설명 문장을 만든다."""
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


def build_esg_reason(esg_assessment: dict[str, Any] | None) -> str:
    """build_esg_reason 함수. 입력 state나 domain 객체를 조합해 downstream에서 사용할 구조화된 payload를 만든다."""
    if not esg_assessment or not esg_assessment.get("pillars"):
        return ""

    pillars = [str(item.get("pillar")) for item in esg_assessment.get("pillars", []) if item.get("pillar")]
    pillar_label = ", ".join(pillars)
    summary = str(esg_assessment.get("summary") or "ESG 관점의 영향 검토가 필요하다.")
    return f"ESG 통합 판단({pillar_label}): {summary}"


def build_status_reason(status: str, risk_score: int, data_accessibility: int, saving_rate: float, risk_flags: list[str] | None = None, discovery_metadata: dict[str, Any] | None = None, discovery_bonus: float = 0.0, compliance_item: dict[str, Any] | None = None, esg_assessment: dict[str, Any] | None = None) -> str:
    """build_status_reason 함수. 입력 state나 domain 객체를 조합해 downstream에서 사용할 구조화된 payload를 만든다."""
    risk_flags = risk_flags or []
    discovery_metadata = discovery_metadata or {}
    suitability_rationale = str(discovery_metadata.get("suitability_rationale") or "").strip()

    if status == "excluded":
        base_reason = "위험도가 매우 높거나 MVP 범위에서 제외해야 하는 업무이다."
    elif status == "human_review_required":
        base_reason = "위험도, 규제 스크리닝 또는 ESG 통합 판단상 Human Review 후 PoC 착수 여부를 결정해야 한다."
    elif status == "data_preparation_required":
        base_reason = "데이터 접근성이 낮아 데이터 정비와 접근권한 확인을 선행해야 한다."
    elif status == "low_roi":
        base_reason = "예상 절감률이 낮아 우선순위에서 후순위로 배치한다."
    elif risk_flags and risk_flags != ["standard_review"]:
        base_reason = "추천 가능하지만 보안·거버넌스 통제 조건을 함께 적용해야 한다."
    else:
        base_reason = "기대효과, 데이터 접근성, 구현 가능성, 위험도를 종합했을 때 PoC 후보로 적합하다."

    esg_reason = build_esg_reason(esg_assessment)
    if esg_reason:
        base_reason = f"{base_reason} {esg_reason}"

    compliance_reason = build_compliance_reason(compliance_item)
    if compliance_reason:
        base_reason = f"{base_reason} Compliance 근거: {compliance_reason}"
    if suitability_rationale:
        return f"{base_reason} Discovery 근거: {suitability_rationale} Discovery bonus={discovery_bonus}."
    return base_reason


def build_roi_map(roi_cost: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    """build_roi_map 함수. 입력 state나 domain 객체를 조합해 downstream에서 사용할 구조화된 payload를 만든다."""
    result: dict[int, dict[str, Any]] = {}
    for item in (roi_cost or {}).get("items", []):
        process_id = safe_int(item.get("process_id"), 0)
        if process_id:
            result[process_id] = item
    return result


def build_risk_map(risk_governance: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    """build_risk_map 함수. 입력 state나 domain 객체를 조합해 downstream에서 사용할 구조화된 payload를 만든다."""
    result: dict[int, dict[str, Any]] = {}
    for item in (risk_governance or {}).get("items", []):
        process_id = safe_int(item.get("process_id"), 0)
        if process_id:
            result[process_id] = item
    return result


def rank_agent_candidates(processes: list[dict[str, Any]], roi_cost: dict[str, Any] | None = None, risk_governance: dict[str, Any] | None = None, compliance_assessment: dict[str, Any] | None = None) -> dict[str, Any]:
    """업무 후보들을 scoring rule로 정렬하고 추천 상태/사유를 붙인다."""
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
        esg_assessment = risk_item.get("esg_assessment", {})

        status = determine_candidate_status(risk_score, data_accessibility, saving_rate, risk_flags)
        status = apply_compliance_status(status, compliance_item)
        reason = build_status_reason(status, risk_score, data_accessibility, saving_rate, risk_flags, discovery_metadata, discovery_bonus, compliance_item, esg_assessment)

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
            "esg_assessment": esg_assessment,
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
    esg_review_required = [item for item in candidates if "esg_review_required" in item.get("risk_flags", [])]

    return {
        "items": candidates,
        "summary": {
            "total_candidates": len(candidates),
            "recommended_count": len(recommended),
            "review_required_count": len(review_required),
            "excluded_count": len(excluded),
            "esg_review_required_count": len(esg_review_required),
            "top_candidate": candidates[0] if candidates else None,
            "compliance_overall_status": (effective_compliance or {}).get("overall_status"),
            "compliance_summary": (effective_compliance or {}).get("summary", {}),
        },
    }
