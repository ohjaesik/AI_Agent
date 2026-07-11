# app/tools/risk_checker.py

"""업무 후보의 privacy/security/high-impact risk signal을 탐지한다.

업무명, 문제, workflow, 문서 metadata, RAG context에서 규칙 기반 risk flag를 만든다.
"""

from __future__ import annotations

from typing import Any


HIGH_RISK_KEYWORDS = [
    "원가",
    "계약",
    "고객사",
    "공급사",
    "개인정보",
    "작업자",
    "징계",
    "인사평가",
    "발주",
    "설비 제어",
    "자동 실행",
    "안전 조치",
]

ESG_KEYWORDS = {
    "environmental": {
        "energy_carbon": [
            "에너지",
            "전력",
            "탄소",
            "온실가스",
            "배출",
            "전력 사용량",
            "energy",
            "carbon",
            "emission",
            "power usage",
        ],
        "resource_efficiency": [
            "자원 효율",
            "폐기물",
            "종이 절감",
            "paperless",
            "waste",
            "resource efficiency",
        ],
    },
    "social": {
        "workforce_impact": [
            "인력 절감",
            "인력 감축",
            "감원",
            "대체",
            "무인화",
            "자동화로 대체",
            "headcount reduction",
            "workforce reduction",
            "job displacement",
            "labor displacement",
        ],
        "employee_monitoring": [
            "작업자 모니터링",
            "직원 모니터링",
            "근태 모니터링",
            "성과 감시",
            "생산성 추적",
            "employee monitoring",
            "worker monitoring",
            "productivity tracking",
            "surveillance",
        ],
        "capability_transition": [
            "재교육",
            "업스킬링",
            "리스킬링",
            "교육 필요",
            "역량 격차",
            "skill gap",
            "reskilling",
            "upskilling",
        ],
        "stakeholder_acceptance": [
            "노조",
            "노사",
            "노동조합",
            "현장 반발",
            "노동 이슈",
            "취약계층",
            "접근성",
            "labor union",
            "worker resistance",
            "accessibility",
            "vulnerable customer",
        ],
    },
    "governance": {
        "compliance_accountability": [
            "법무",
            "규제",
            "감사",
            "승인",
            "책임자",
            "컴플라이언스",
            "compliance",
            "audit",
            "approval",
            "accountability",
        ],
        "privacy_security": [
            "개인정보",
            "고객정보",
            "기밀",
            "보안",
            "접근권한",
            "personal data",
            "privacy",
            "confidential",
            "security",
        ],
        "ai_governance": [
            "설명가능성",
            "투명성",
            "휴먼리뷰",
            "사람 검토",
            "human review",
            "explainability",
            "transparency",
            "ai governance",
        ],
    },
}

SENSITIVE_SECURITY_LEVELS = {"confidential", "restricted"}


def safe_int(value: Any, default: int = 0) -> int:
    """None/문자열/잘못된 값을 안전하게 정수로 변환한다."""
    if value is None:
        return default

    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def contains_high_risk_keyword(text: str | None) -> list[str]:
    """contains_high_risk_keyword 함수. 조건을 검사해 True/False 판단값을 반환한다."""
    if not text:
        return []

    return [keyword for keyword in HIGH_RISK_KEYWORDS if keyword in text]


def detect_esg_signals(text: str | None) -> dict[str, dict[str, list[str]]]:
    """detect_esg_signals 함수. 텍스트/state에서 특정 신호나 risk flag를 탐지한다."""
    if not text:
        return {}

    normalized = text.lower()
    matches: dict[str, dict[str, list[str]]] = {}
    for pillar, categories in ESG_KEYWORDS.items():
        for category, keywords in categories.items():
            hits = [keyword for keyword in keywords if keyword.lower() in normalized]
            if hits:
                matches.setdefault(pillar, {})[category] = hits
    return matches


def merge_esg_signals(
    base: dict[str, dict[str, list[str]]],
    addition: dict[str, dict[str, list[str]]],
) -> dict[str, dict[str, list[str]]]:
    """merge_esg_signals 함수. 업무 후보의 privacy/security/high-impact risk signal을 탐지한다. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    for pillar, categories in addition.items():
        base.setdefault(pillar, {})
        for category, hits in categories.items():
            base[pillar].setdefault(category, [])
            base[pillar][category].extend(hits)
    return base


def flatten_esg_pillars(signals: dict[str, dict[str, list[str]]]) -> list[dict[str, Any]]:
    """flatten_esg_pillars 함수. 업무 후보의 privacy/security/high-impact risk signal을 탐지한다. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    result = []
    for pillar, categories in sorted(signals.items()):
        result.append(
            {
                "pillar": pillar,
                "categories": sorted(categories),
                "matched_keywords": sorted(set(hit for hits in categories.values() for hit in hits)),
            }
        )
    return result


def build_esg_controls(signals: dict[str, dict[str, list[str]]]) -> list[str]:
    """build_esg_controls 함수. 입력 state나 domain 객체를 조합해 downstream에서 사용할 구조화된 payload를 만든다."""
    controls: list[str] = []
    environmental = signals.get("environmental", {})
    social = signals.get("social", {})
    governance = signals.get("governance", {})

    if environmental:
        controls.append("환경 관점에서는 Agent 도입이 에너지·탄소·자원 사용량에 미치는 영향과 산정 근거를 함께 기록한다.")
    if "workforce_impact" in social:
        controls.append("사회 관점에서는 인력 감축 목적이 아니라 업무 보조·직무 전환·재교육 관점으로 PoC 범위를 제한한다.")
    if "employee_monitoring" in social:
        controls.append("사회 관점에서는 직원·작업자 모니터링 데이터를 개인 징계·인사평가 자동화에 직접 사용하지 않는다.")
    if "capability_transition" in social:
        controls.append("사회 관점에서는 Agent 도입에 따른 사용자 교육·업스킬링·리스킬링 계획을 포함한다.")
    if "stakeholder_acceptance" in social:
        controls.append("사회 관점에서는 현업·노사·고객 등 이해관계자 수용성과 대체 경로를 Human Review에서 확인한다.")
    if governance:
        controls.append("거버넌스 관점에서는 책임자, 승인권자, 감사 로그, 설명가능성, 접근권한을 PoC 착수 전 확인한다.")

    return controls


def build_esg_assessment(signals: dict[str, dict[str, list[str]]]) -> dict[str, Any]:
    """build_esg_assessment 함수. 입력 state나 domain 객체를 조합해 downstream에서 사용할 구조화된 payload를 만든다."""
    pillars = flatten_esg_pillars(signals)
    controls = build_esg_controls(signals)
    review_required = bool(signals.get("social") or signals.get("governance"))
    impact_level = "review_required" if review_required else "opportunity" if signals.get("environmental") else "none"

    if not pillars:
        summary = "ESG 관점에서 별도 검토 신호가 탐지되지 않았다."
    elif review_required:
        summary = "Agent 도입이 ESG 관점에서 이해관계자, 데이터 거버넌스, 책임성 또는 운영 통제에 영향을 줄 수 있어 통합 ESG Review가 필요하다."
    else:
        summary = "Agent 도입이 환경 효율 관점의 긍정 효과를 가질 수 있으나 산정 근거 확인이 필요하다."

    return {
        "impact_level": impact_level,
        "review_required": review_required,
        "pillars": pillars,
        "required_controls": controls,
        "summary": summary,
    }


def determine_risk_level(risk_score: int) -> str:
    """determine_risk_level 함수. 업무 후보의 privacy/security/high-impact risk signal을 탐지한다. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    if risk_score >= 5:
        return "critical"
    if risk_score >= 4:
        return "high"
    if risk_score >= 3:
        return "medium"
    return "low"


def check_process_risk(
    process: dict[str, Any],
    related_contexts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    업무 1개에 대한 rule-based governance risk check.

    LLM이 위험 설명을 생성하더라도, 아래 규칙은 고정적으로 적용한다.
    """
    process_id = safe_int(process.get("id"))
    risk_score = safe_int(process.get("risk_score"), 3)
    data_accessibility = safe_int(process.get("data_accessibility"), 3)

    name = process.get("name") or ""
    problem = process.get("problem") or ""
    workflow = process.get("current_workflow") or ""
    candidate = process.get("candidate_agent_name") or ""
    target_user = process.get("target_user") or ""
    security_level = process.get("security_level") or "internal"

    combined_text = "\n".join([name, problem, workflow, candidate, target_user])
    matched_keywords = contains_high_risk_keyword(combined_text)
    esg_signals = detect_esg_signals(combined_text)

    context_sensitive = False
    context_titles: list[str] = []

    for context in related_contexts or []:
        if context.get("contains_sensitive_info"):
            context_sensitive = True
            context_titles.append(str(context.get("title")))

        context_security = context.get("security_level")
        if context_security in SENSITIVE_SECURITY_LEVELS:
            context_sensitive = True
            context_titles.append(str(context.get("title")))

        context_text = "\n".join([
            str(context.get("title") or ""),
            str(context.get("text") or context.get("content") or context.get("snippet") or ""),
        ])
        esg_signals = merge_esg_signals(esg_signals, detect_esg_signals(context_text))

    esg_assessment = build_esg_assessment(esg_signals)

    flags: list[str] = []
    controls: list[str] = []

    if risk_score >= 4:
        flags.append("human_review_required")
        controls.append("위험도 4 이상 업무이므로 Human Review 후 PoC 착수 여부를 결정한다.")

    if data_accessibility <= 2:
        flags.append("data_preparation_required")
        controls.append("데이터 접근성 2 이하이므로 데이터 정비와 접근권한 확인을 선행한다.")

    if security_level in SENSITIVE_SECURITY_LEVELS:
        flags.append("security_review_required")
        controls.append("보안등급이 높은 업무이므로 권한 기반 접근제어와 감사 로그를 적용한다.")

    if matched_keywords:
        flags.append("sensitive_keyword_detected")
        controls.append("민감 키워드가 포함되어 있으므로 LLM 입력 전 마스킹과 검토 절차를 적용한다.")

    if context_sensitive:
        flags.append("sensitive_context_detected")
        controls.append("검색된 근거 문서에 민감정보가 포함될 수 있으므로 RAG 결과 노출 범위를 제한한다.")

    if esg_assessment["pillars"]:
        flags.append("esg_assessment_present")
        controls.extend(esg_assessment["required_controls"])
    if esg_assessment["review_required"]:
        flags.append("esg_review_required")

    if "발주" in name or "발주" in candidate:
        flags.append("execution_not_allowed")
        controls.append("발주 업무는 AI가 자동 실행하지 않고 담당자와 팀장 승인 후 처리한다.")

    if "인사" in name or "징계" in problem or "인사평가" in combined_text:
        flags.append("excluded_from_mvp")
        controls.append("인사평가·징계 관련 업무는 MVP 범위에서 제외한다.")

    if not flags:
        flags.append("standard_review")
        controls.append("표준 승인 절차와 기본 감사 로그를 적용한다.")

    return {
        "process_id": process_id,
        "process_name": name,
        "candidate_agent_name": candidate,
        "risk_score": risk_score,
        "risk_level": determine_risk_level(risk_score),
        "security_level": security_level,
        "matched_keywords": matched_keywords,
        "sensitive_context_titles": sorted(set(context_titles)),
        "flags": sorted(set(flags)),
        "controls": controls,
        "esg_assessment": esg_assessment,
    }


def check_risks_for_processes(
    processes: list[dict[str, Any]],
    retrieved_contexts: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """전체 업무 후보에 대해 규칙 기반 risk flag와 통제 필요성을 계산한다."""
    retrieved_contexts = retrieved_contexts or {}

    items = [
        check_process_risk(
            process=process,
            related_contexts=retrieved_contexts.get(str(process.get("id")), []),
        )
        for process in processes
    ]

    high_risk_count = sum(
        1 for item in items if item["risk_level"] in {"high", "critical"}
    )

    review_required_count = sum(
        1 for item in items if "human_review_required" in item["flags"]
    )

    esg_assessment_count = sum(
        1 for item in items if "esg_assessment_present" in item["flags"]
    )

    esg_review_required_count = sum(
        1 for item in items if "esg_review_required" in item["flags"]
    )

    return {
        "items": items,
        "summary": {
            "total_processes": len(items),
            "high_risk_count": high_risk_count,
            "review_required_count": review_required_count,
            "esg_assessment_count": esg_assessment_count,
            "esg_review_required_count": esg_review_required_count,
        },
    }
