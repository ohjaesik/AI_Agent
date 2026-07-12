# app/compliance/assessment.py

"""후보 업무의 개인정보/보안/고영향/금지 가능 사용 리스크를 평가한다.

risk_governance 결과와 업무 metadata를 바탕으로 compliance level, blocked 여부,
human review 필요 여부, 필요한 통제 항목을 산출한다.
"""

from __future__ import annotations

from typing import Any

from app.agents.registry import get_agent_registry
from app.compliance.regulatory_mapping import (
    build_regulatory_mappings,
    get_regulatory_mapping_rules,
    summarize_regulatory_mappings,
)
from app.compliance.regulatory_policy import (
    get_korea_ai_basic_act_reference,
    get_regulatory_controls,
)

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

# 일반 검토 flag까지 sensitive_review로 끌어올리면 모든 후보가 과도하게 보수 분류된다.
# sensitive_review는 실제 민감정보/기밀/보안 문맥 flag에만 적용한다.
SENSITIVE_RISK_FLAGS = {
    "contains_sensitive_keyword",
    "sensitive_document_context",
    "contains_personal_data",
    "contains_confidential_data",
    "contains_trade_secret",
    "restricted_access_required",
    "security_sensitive",
}

HIGH_IMPACT_RISK_FLAGS = {
    "high_impact_ai_possible",
    "safety_critical",
    "legal_decision_support",
    "employment_decision_support",
    "financial_decision_support",
    "medical_decision_support",
    "critical_infrastructure",
}

KOREA_AI_BASIC_ACT_REQUIREMENTS = {
    "standard": [
        "AI 보조 산출물 고지",
        "근거 source 및 생성 방식 기록",
        "사람 승인 전 최종 의사결정 사용 금지",
    ],
    "sensitive_review": [
        "민감정보·기밀정보 포함 가능성 검토",
        "접근권한 및 데이터 최소화 확인",
        "Human Review 및 보안 owner 검토 필요",
    ],
    "enhanced_review": [
        "고영향 AI 가능성 사전 검토",
        "사람 감독 체계 및 책임자 지정",
        "설명가능성·기록관리·데이터 품질 증빙 필요",
        "법무·보안 owner 승인 전 PoC 착수 금지",
    ],
    "blocked": [
        "부적절 또는 금지 가능성이 있는 활용으로 MVP 후보 제외",
        "법무 검토 없이 추천·PoC 진행 금지",
    ],
}


def normalize_text(*values: Any) -> str:
    """normalize_text 함수. 비교/저장/출력을 안정화하기 위해 입력값 형식을 정규화한다."""
    return " ".join(str(value or "") for value in values).lower()


def find_keywords(text: str, keywords: list[str]) -> list[str]:
    """정규화된 후보 설명에서 규제/민감정보 keyword가 실제로 등장한 항목만 반환한다."""
    return [keyword for keyword in keywords if keyword.lower() in text]


def classify_high_impact(text: str) -> list[str]:
    """고영향 가능성이 있는 도메인 category를 keyword 기반으로 분류한다."""
    categories = []
    for category, keywords in HIGH_IMPACT_KEYWORDS.items():
        if find_keywords(text, keywords):
            categories.append(category)
    return categories


def korea_ai_basic_act_requirements_for_level(level: str) -> list[str]:
    """compliance level에 맞는 한국 AI 기본법 대응 요구사항 목록을 반환한다."""
    return KOREA_AI_BASIC_ACT_REQUIREMENTS.get(level, KOREA_AI_BASIC_ACT_REQUIREMENTS["standard"])


def classify_process(process: dict[str, Any], risk_item: dict[str, Any] | None = None) -> dict[str, Any]:
    """업무 후보 하나를 standard/sensitive/enhanced/blocked compliance level로 분류한다."""
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
    risk_flags = [str(flag) for flag in (risk_item.get("flags", []) or [])]
    sensitive_risk_flags = sorted(set(flag for flag in risk_flags if flag in SENSITIVE_RISK_FLAGS))
    high_impact_risk_flags = sorted(set(flag for flag in risk_flags if flag in HIGH_IMPACT_RISK_FLAGS))

    for flag in sensitive_risk_flags:
        sensitive_hits.append(flag)
    for flag in high_impact_risk_flags:
        if flag not in high_impact_categories:
            high_impact_categories.append(flag)

    required_controls = [
        "traceability_logging",
        "transparency_disclosure",
        "explainability_notice",
        "assistive_use_boundary",
    ]
    blocked = False
    human_review_required = False
    compliance_level = "standard"

    if prohibited_hits:
        blocked = True
        human_review_required = True
        compliance_level = "blocked"
        required_controls.extend(["prohibited_use_screening", "human_oversight", "safety_reliability_management"])
    elif high_impact_categories:
        human_review_required = True
        compliance_level = "enhanced_review"
        required_controls.extend(["high_impact_screening", "human_oversight", "data_quality_governance", "safety_reliability_management"])
    elif sensitive_hits or sensitive_risk_flags:
        human_review_required = True
        compliance_level = "sensitive_review"
        required_controls.extend(["security_privacy_controls", "human_oversight", "data_quality_governance"])

    regulatory_mappings = build_regulatory_mappings(
        compliance_level=compliance_level,
        prohibited_hits=prohibited_hits,
        high_impact_categories=high_impact_categories,
        sensitive_hits=sensitive_hits,
        sensitive_risk_flags=sensitive_risk_flags,
        high_impact_risk_flags=high_impact_risk_flags,
        risk_flags=risk_flags,
    )
    regulatory_summary = summarize_regulatory_mappings(regulatory_mappings)
    for control in regulatory_summary["required_controls"]:
        if control not in required_controls:
            required_controls.append(control)

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
        "high_impact_categories": sorted(set(high_impact_categories)),
        "sensitive_hits": sorted(set(sensitive_hits)),
        "risk_flags": risk_flags,
        "sensitive_risk_flags": sensitive_risk_flags,
        "high_impact_risk_flags": high_impact_risk_flags,
        "required_controls": deduped_controls,
        "korea_ai_basic_act_requirements": korea_ai_basic_act_requirements_for_level(compliance_level),
        "regulatory_mappings": regulatory_mappings,
        "regulatory_summary": regulatory_summary,
    }


def build_risk_map(risk_governance: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    """risk_governance 결과를 process_id 기준으로 찾아볼 수 있게 변환한다."""
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
    """전체 업무 후보에 compliance 분류를 적용하고 dashboard/report용 summary를 만든다."""
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
    framework_counts: dict[str, int] = {}
    risk_category_counts: dict[str, int] = {}
    for item in items:
        for framework in (item.get("regulatory_summary") or {}).get("frameworks", []):
            framework_counts[framework] = framework_counts.get(framework, 0) + 1
        for risk_category in (item.get("regulatory_summary") or {}).get("risk_categories", []):
            risk_category_counts[risk_category] = risk_category_counts.get(risk_category, 0) + 1

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
            "framework_counts": framework_counts,
            "risk_category_counts": risk_category_counts,
        },
        "agent_registry": get_agent_registry(),
        "regulatory_controls": get_regulatory_controls(),
        "regulatory_mapping_rules": get_regulatory_mapping_rules(),
        "korea_ai_basic_act_reference": get_korea_ai_basic_act_reference(),
        "disclaimer": (
            "This assessment is a technical compliance screening for AX planning. "
            "It is not legal advice and should be reviewed by legal/security owners before production deployment. "
            "Korea AI Basic Act mapping is an operational control mapping and must be checked against official law, decree, and guidance before production use."
        ),
    }
