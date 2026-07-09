# app/tools/risk_checker.py

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

ESG_SOCIAL_KEYWORDS = {
    "workforce_displacement": [
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
    "skill_gap": [
        "재교육",
        "업스킬링",
        "리스킬링",
        "교육 필요",
        "역량 격차",
        "skill gap",
        "reskilling",
        "upskilling",
    ],
    "labor_relation": [
        "노조",
        "노사",
        "노동조합",
        "현장 반발",
        "노동 이슈",
        "labor union",
        "labor relation",
        "worker resistance",
    ],
    "service_accessibility": [
        "상담 자동화",
        "고객 응대 자동화",
        "민원 자동화",
        "취약계층",
        "접근성",
        "customer service automation",
        "accessibility",
        "vulnerable customer",
    ],
}

SENSITIVE_SECURITY_LEVELS = {"confidential", "restricted"}


def safe_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default

    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def contains_high_risk_keyword(text: str | None) -> list[str]:
    if not text:
        return []

    return [keyword for keyword in HIGH_RISK_KEYWORDS if keyword in text]


def contains_esg_social_keywords(text: str | None) -> dict[str, list[str]]:
    if not text:
        return {}

    normalized = text.lower()
    matches: dict[str, list[str]] = {}
    for category, keywords in ESG_SOCIAL_KEYWORDS.items():
        hits = [keyword for keyword in keywords if keyword.lower() in normalized]
        if hits:
            matches[category] = hits
    return matches


def build_esg_social_controls(categories: list[str]) -> list[str]:
    controls = []
    if "workforce_displacement" in categories:
        controls.append("인력 대체 효과가 예상되는 업무는 인력 감축 목적이 아니라 업무 보조·재배치·역량 전환 관점으로 PoC 범위를 제한한다.")
        controls.append("PoC 착수 전 현업 영향도, 직무 변화, 재교육 계획을 Human Review에서 확인한다.")
    if "employee_monitoring" in categories:
        controls.append("직원·작업자 모니터링 성격의 데이터는 개인 징계·인사평가 자동화에 직접 사용하지 않는다.")
        controls.append("개인 단위 추적보다 라인·팀·프로세스 단위의 집계 지표를 우선 사용한다.")
    if "skill_gap" in categories:
        controls.append("Agent 도입으로 필요한 업무 역량 변화를 정의하고 사용자 교육·전환 지원 계획을 포함한다.")
    if "labor_relation" in categories:
        controls.append("노사·현장 수용성 이슈가 예상되면 PoC 범위와 데이터 사용 목적을 사전에 설명하고 의견 수렴 절차를 둔다.")
    if "service_accessibility" in categories:
        controls.append("고객 응대 자동화는 취약계층·비디지털 사용자에게 사람 상담 경로를 유지한다.")
    return controls


def determine_risk_level(risk_score: int) -> str:
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
    esg_social_matches = contains_esg_social_keywords(combined_text)
    esg_social_categories = sorted(esg_social_matches)

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
        context_esg_matches = contains_esg_social_keywords(context_text)
        for category, hits in context_esg_matches.items():
            esg_social_matches.setdefault(category, [])
            esg_social_matches[category].extend(hits)
        esg_social_categories = sorted(esg_social_matches)

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

    if esg_social_categories:
        flags.append("social_impact_review_required")
        controls.extend(build_esg_social_controls(esg_social_categories))
        if "workforce_displacement" in esg_social_categories:
            flags.append("workforce_transition_required")
        if "employee_monitoring" in esg_social_categories:
            flags.append("employee_monitoring_guardrail_required")
        if "skill_gap" in esg_social_categories:
            flags.append("reskilling_plan_required")
        if "labor_relation" in esg_social_categories:
            flags.append("labor_stakeholder_review_required")
        if "service_accessibility" in esg_social_categories:
            flags.append("accessibility_fallback_required")

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
        "esg_social_risks": [
            {"category": category, "matched_keywords": sorted(set(hits))}
            for category, hits in sorted(esg_social_matches.items())
        ],
        "esg_social_controls": build_esg_social_controls(esg_social_categories),
    }


def check_risks_for_processes(
    processes: list[dict[str, Any]],
    retrieved_contexts: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
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

    social_impact_review_count = sum(
        1 for item in items if "social_impact_review_required" in item["flags"]
    )

    return {
        "items": items,
        "summary": {
            "total_processes": len(items),
            "high_risk_count": high_risk_count,
            "review_required_count": review_required_count,
            "social_impact_review_count": social_impact_review_count,
        },
    }
