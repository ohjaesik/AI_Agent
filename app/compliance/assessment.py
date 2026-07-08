# app/compliance/assessment.py

from __future__ import annotations

from typing import Any

from app.agents.registry import get_agent_registry
from app.compliance.regulatory_policy import get_regulatory_controls

PROHIBITED_KEYWORDS = [
    "사회적 점수",
    "social scoring",
    "무차별 얼굴 인식",
    "facial recognition database",
    "감정 인식",
    "emotion recognition",
    "취약성 악용",
    "vulnerability exploitation",
    "잠재의식 조작",
    "subliminal",
    "범죄 예측",
    "predictive policing",
]

HIGH_IMPACT_KEYWORDS = {
    "employment": ["채용", "인사", "근태", "평가", "승진", "해고", "recruit", "hr", "employment"],
    "finance": ["금융", "대출", "신용", "보험", "credit", "loan", "finance"],
    "healthcare": ["의료", "진단", "환자", "health", "medical", "diagnosis"],
    "critical_infrastructure": ["원전", "전력", "수도", "교통", "운송", "nuclear", "transport", "water", "grid"],
    "education": ["교육", "시험", "성적", "입학", "student", "exam", "education"],
    "law_public_service": ["법률", "소송", "복지", "공공서비스", "court", "welfare", "public service"],
}

SENSITIVE_KEYWORDS = [
    "개인정보",
    "주민등록번호",
    "계좌",
    "비밀번호",
    "영업비밀",
    "기밀",
    "특허",
    "지식재산",
    "고객정보",
    "personal data",
    "trade secret",
    "confidential",
]


def normalize_text(*values: Any) -> str:
    return " ".join(str(value or "") for value in values).lower()


def find_keywords(text: str, keywords: list[str]) -> list[str]:
    return [keyword for keyword in keywords if keyword.lower() in text]


def classify_high_impact(text: str) -> list[str]:
    categories = []
    for category, keywords in HIGH_IMPACT_KEYWORDS.items():
        if find_keywords(text, keywords):
            categories.append(category)
    return categories


def classify_process(process: dict[str, Any], risk_item: dict[str, Any] | None = None) -> dict[str, Any]:
    text = normalize_text(
        process.get("name"),
        process.get("problem"),
        process.get("current_workflow"),
        process.get("candidate_agent_name"),
        process.get("target_user"),
        process.get("security_level"),
    )

    prohibited_hits = find_keywords(text, PROHIBITED_KEYWORDS)
    high_impact_categories = classify_high_impact(text)
    sensitive_hits = find_keywords(text, SENSITIVE_KEYWORDS)

    risk_item = risk_item or {}
    risk_flags = risk_item.get("flags", []) or []
    if any(flag in risk_flags for flag in ["contains_sensitive_keyword", "sensitive_document_context"]):
        sensitive_hits.append("risk_governance_sensitive_flag")

    required_controls = [
        "traceability_logging",
        "transparency_disclosure",
        "assistive_use_boundary",
    ]
    blocked = False
    human_review_required = False
    compliance_level = "standard"

    if prohibited_hits:
        blocked = True
        human_review_required = True
        compliance_level = "blocked"
        required_controls.extend(["prohibited_use_screening", "human_oversight"])
    elif high_impact_categories:
        human_review_required = True
        compliance_level = "enhanced_review"
        required_controls.extend(["high_impact_screening", "human_oversight", "data_quality_governance"])
    elif sensitive_hits or risk_flags:
        human_review_required = True
        compliance_level = "sensitive_review"
        required_controls.extend(["security_privacy_controls", "human_oversight"])

    # 중복 제거
    deduped_controls = []
    for control in required_controls:
        if control not in deduped_controls:
            deduped_controls.append(control)

    return {
        "process_id": process.get("id"),
        "process_name": process.get("name"),
        "candidate_agent_name": process.get("candidate_agent_name"),
        "compliance_level": compliance_level,
        "blocked": blocked,
        "human_review_required": human_review_required,
        "prohibited_hits": prohibited_hits,
        "high_impact_categories": high_impact_categories,
        "sensitive_hits": sorted(set(sensitive_hits)),
        "risk_flags": risk_flags,
        "required_controls": deduped_controls,
    }


def build_risk_map(risk_governance: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for item in (risk_governance or {}).get("items", []):
        try:
            process_id = int(item.get("process_id"))
        except (TypeError, ValueError):
            continue
        result[process_id] = item
    return result


def assess_ai_compliance(
    processes: list[dict[str, Any]],
    risk_governance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    risk_map = build_risk_map(risk_governance)
    items = []

    for process in processes:
        try:
            process_id = int(process.get("id"))
        except (TypeError, ValueError):
            process_id = 0
        items.append(classify_process(process, risk_item=risk_map.get(process_id)))

    blocked_items = [item for item in items if item["blocked"]]
    enhanced_items = [item for item in items if item["compliance_level"] == "enhanced_review"]
    sensitive_items = [item for item in items if item["compliance_level"] == "sensitive_review"]
    human_review_items = [item for item in items if item["human_review_required"]]

    overall_status = "pass"
    if blocked_items:
        overall_status = "blocked"
    elif enhanced_items or sensitive_items:
        overall_status = "review_required"

    return {
        "overall_status": overall_status,
        "items": items,
        "summary": {
            "total_processes": len(items),
            "blocked_count": len(blocked_items),
            "enhanced_review_count": len(enhanced_items),
            "sensitive_review_count": len(sensitive_items),
            "human_review_required_count": len(human_review_items),
        },
        "agent_registry": get_agent_registry(),
        "regulatory_controls": get_regulatory_controls(),
        "disclaimer": (
            "This assessment is a technical compliance screening for AX planning. "
            "It is not legal advice and should be reviewed by legal/security owners before production deployment."
        ),
    }
