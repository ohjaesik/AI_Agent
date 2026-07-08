# app/tools/deterministic_report_data_builder.py

from __future__ import annotations

from datetime import date
from typing import Any


def money(value: Any) -> str:
    try:
        return f"{int(value):,}원"
    except (TypeError, ValueError):
        return "0원"


def percent(value: Any) -> str:
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "0.0%"


def evidence_for(
    evidence_items: list[dict[str, Any]],
    purpose: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    matched = [
        item
        for item in evidence_items
        if purpose in item.get("used_for", [])
    ]

    matched.sort(
        key=lambda item: float(item.get("confidence") or 0.0),
        reverse=True,
    )

    return matched[:limit]


def citations(items: list[dict[str, Any]]) -> str:
    labels = []

    for item in items:
        label = item.get("citation_label")
        if label and label not in labels:
            labels.append(label)

    return " ".join(labels)


def summarize_evidence(items: list[dict[str, Any]], limit: int = 3) -> str:
    selected = items[:limit]

    if not selected:
        return "현재 연결된 근거 자료가 부족하여 추가 자료 수집이 필요하다."

    sentences = []

    for item in selected:
        title = item.get("title", "근거 문서")
        summary = item.get("summary") or item.get("content", "")[:200]
        label = item.get("citation_label", "")
        sentences.append(f"{title}에 따르면 {summary} {label}")

    return " ".join(sentences)


def build_process_rows(state: dict[str, Any]) -> list[list[Any]]:
    rows = []

    for process in state.get("business_processes", []):
        rows.append(
            [
                process.get("name"),
                process.get("target_user"),
                process.get("candidate_agent_name"),
                process.get("expected_effect"),
                process.get("data_accessibility"),
                process.get("risk_score"),
            ]
        )

    return rows


def build_candidate_rows(state: dict[str, Any]) -> list[list[Any]]:
    rows = []

    for item in state.get("priority_ranking", {}).get("items", []):
        rows.append(
            [
                item.get("rank"),
                item.get("candidate_agent_name"),
                item.get("target_user"),
                item.get("final_score"),
                item.get("status"),
                percent(item.get("saving_rate")),
                item.get("reason"),
            ]
        )

    return rows


def build_roi_rows(state: dict[str, Any]) -> list[list[Any]]:
    rows = []

    for item in state.get("roi_cost", {}).get("items", []):
        rows.append(
            [
                item.get("process_name"),
                item.get("candidate_agent_name"),
                money(item.get("monthly_current_cost")),
                money(item.get("monthly_expected_cost")),
                money(item.get("monthly_saving")),
                percent(item.get("saving_rate")),
            ]
        )

    return rows


def build_risk_rows(state: dict[str, Any]) -> list[list[Any]]:
    rows = []

    for item in state.get("risk_governance", {}).get("items", []):
        rows.append(
            [
                item.get("process_name"),
                item.get("candidate_agent_name"),
                item.get("risk_score"),
                item.get("risk_level"),
                ", ".join(item.get("flags", [])),
            ]
        )

    return rows


def build_report_data(state: dict[str, Any]) -> dict[str, Any]:
    company = state.get("company_profile", {})
    evidence_items = state.get("evidence_items", [])
    used_sources = state.get("used_sources", [])
    roi_summary = state.get("roi_cost", {}).get("summary", {})
    ranking = state.get("priority_ranking", {})
    top_candidate = ranking.get("summary", {}).get("top_candidate") or {}

    industry_evidence = evidence_for(evidence_items, "industry_analysis")
    process_evidence = evidence_for(evidence_items, "business_process_analysis")
    report_evidence = evidence_for(evidence_items, "report_generation", limit=10)

    report_requirements = state.get("report_requirements", {})

    title = report_requirements.get(
        "title",
        "제조기업 AX 전환 업무 프로세스 진단 및 AI Agent 도입 우선순위 추천 보고서",
    )

    author = report_requirements.get("author", "")
    date_value = report_requirements.get("date", str(date.today()))

    return {
        "title": title,
        "author": author,
        "date": date_value,
        "company_name": company.get("name", ""),
        "mvp_agent": top_candidate.get("candidate_agent_name") or "AX Delivery Planner",
        "sections": [
            {
                "heading": "1. 분석 목적 및 범위",
                "blocks": [
                    {
                        "type": "paragraph",
                        "text": (
                            f"본 보고서는 {company.get('name', '분석 대상 기업')}의 "
                            f"업무 프로세스와 보유 문서를 기반으로 AI Agent 도입 후보를 분석하고 "
                            f"PoC 우선순위를 제안하기 위해 작성되었다. "
                            f"분석에는 내부 업무 프로세스 {len(state.get('business_processes', []))}개, "
                            f"문서 근거 {len(evidence_items)}개가 사용되었다. "
                            f"{citations(report_evidence)}"
                        ),
                    },
                    {
                        "type": "paragraph",
                        "text": (
                            "본 보고서의 내용은 고정 템플릿이 아니라 DB에 등록된 업무 데이터, "
                            "RAG 검색 결과, Agent 분석 결과를 바탕으로 생성된다."
                        ),
                    },
                ],
            },
            {
                "heading": "2. 기업 및 산업 특성 분석",
                "blocks": [
                    {
                        "type": "paragraph",
                        "text": (
                            f"분석 대상 기업은 {company.get('industry', '제조업')}에 속하는 "
                            f"{company.get('size', '기업')}이며, "
                            f"{company.get('description', '')} "
                            f"{citations(industry_evidence)}"
                        ),
                    },
                    {
                        "type": "paragraph",
                        "text": summarize_evidence(industry_evidence),
                    },
                ],
            },
            {
                "heading": "3. 업무 프로세스 및 데이터 현황",
                "blocks": [
                    {
                        "type": "paragraph",
                        "text": (
                            "업무 프로세스 분석은 DB에 등록된 부서별 업무, 대상 사용자, 문제 정의, "
                            "현재 workflow, 데이터 접근성, 위험도 점수를 기반으로 수행되었다. "
                            f"{citations(process_evidence)}"
                        ),
                    },
                    {
                        "type": "table",
                        "headers": [
                            "업무명",
                            "대상 사용자",
                            "후보 Agent",
                            "기대효과",
                            "데이터 접근성",
                            "위험도",
                        ],
                        "rows": build_process_rows(state),
                        "font_size": 7,
                    },
                ],
            },
            {
                "heading": "4. AI Agent 후보 우선순위 분석",
                "blocks": [
                    {
                        "type": "paragraph",
                        "text": (
                            "우선순위는 기대효과, 데이터 접근성, 반복성, 구현 용이성, "
                            "현업 수용성, 보안·거버넌스 위험, 구현 비용을 기준으로 계산하였다. "
                            "점수 계산은 LLM이 아니라 Python Tool로 수행하여 재현성을 확보하였다."
                        ),
                    },
                    {
                        "type": "table",
                        "headers": [
                            "순위",
                            "후보 Agent",
                            "대상 사용자",
                            "점수",
                            "상태",
                            "절감률",
                            "추천 사유",
                        ],
                        "rows": build_candidate_rows(state),
                        "font_size": 7,
                    },
                ],
            },
            {
                "heading": "5. ROI 및 비용 절감 분석",
                "blocks": [
                    {
                        "type": "paragraph",
                        "text": (
                            f"분석 결과 월간 현재 비용은 {money(roi_summary.get('total_current_cost'))}, "
                            f"Agent 보조 이후 예상 비용은 {money(roi_summary.get('total_expected_cost'))}, "
                            f"예상 절감액은 {money(roi_summary.get('total_saving'))}, "
                            f"절감률은 {percent(roi_summary.get('total_saving_rate'))}로 계산되었다."
                        ),
                    },
                    {
                        "type": "table",
                        "headers": [
                            "업무",
                            "후보 Agent",
                            "현재 비용",
                            "예상 비용",
                            "절감액",
                            "절감률",
                        ],
                        "rows": build_roi_rows(state),
                        "font_size": 7,
                    },
                ],
            },
            {
                "heading": "6. 보안 및 Governance 위험 분석",
                "blocks": [
                    {
                        "type": "paragraph",
                        "text": (
                            "위험 분석은 업무별 보안등급, 민감 키워드, 데이터 접근성, "
                            "RAG로 검색된 문서의 민감정보 여부를 기준으로 수행되었다."
                        ),
                    },
                    {
                        "type": "table",
                        "headers": [
                            "업무",
                            "후보 Agent",
                            "위험점수",
                            "위험등급",
                            "위험 플래그",
                        ],
                        "rows": build_risk_rows(state),
                        "font_size": 7,
                    },
                ],
            },
            {
                "heading": "7. 최종 PoC 제안",
                "blocks": [
                    {
                        "type": "paragraph",
                        "text": (
                            f"최상위 후보는 {top_candidate.get('candidate_agent_name', '확인 필요')}이며, "
                            f"최종 점수는 {top_candidate.get('final_score', 'N/A')}이다. "
                            f"선정 사유는 다음과 같다: {top_candidate.get('reason', '추가 분석 필요')}"
                        ),
                    },
                    {
                        "type": "paragraph",
                        "text": (
                            "단, 최종 PoC 착수 여부는 Human Review를 통해 현업 부서장, "
                            "IT기획팀, 보안 담당자의 승인을 받은 뒤 결정해야 한다."
                        ),
                    },
                ],
            },
        ],
        "references": used_sources,
    }
