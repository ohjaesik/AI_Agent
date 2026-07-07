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
    security_level = process.get("security_level") or "internal"

    combined_text = "\n".join([name, problem, workflow, candidate])
    matched_keywords = contains_high_risk_keyword(combined_text)

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

    return {
        "items": items,
        "summary": {
            "total_processes": len(items),
            "high_risk_count": high_risk_count,
            "review_required_count": review_required_count,
        },
    }