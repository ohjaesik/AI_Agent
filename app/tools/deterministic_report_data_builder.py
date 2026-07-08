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


def evidence_for(evidence_items: list[dict[str, Any]], purpose: str, limit: int = 5) -> list[dict[str, Any]]:
    matched = [item for item in evidence_items if purpose in item.get("used_for", [])]
    matched.sort(key=lambda item: float(item.get("confidence") or 0.0), reverse=True)
    return matched[:limit]


def citations(items: list[dict[str, Any]]) -> str:
    labels = []
    for item in items:
        label = item.get("citation_label")
        if label and label not in labels:
            labels.append(label)
    return " ".join(labels)


def source_label_for_document(document: dict[str, Any], index: int) -> str:
    document_type = str(document.get("document_type") or "")
    if document_type == "opendart_company_overview":
        return "[DART-기업개황]"
    if document_type == "official_url":
        return f"[공식URL-{index}]"
    return f"[내부문서-{document.get('id', index)}]"


def clean_company_description(description: str | None) -> list[str]:
    if not description:
        return []

    # 과거 버전에서 저장된 raw scraped text를 보고서에 노출하지 않기 위해 잘라낸다.
    description = description.split("공식자료 요약 단서:")[0]
    lines = []
    for line in description.splitlines():
        cleaned = " ".join(line.split()).strip()
        if not cleaned:
            continue
        if len(cleaned) > 140:
            cleaned = cleaned[:140] + "..."
        lines.append(cleaned)
    return lines


def extract_profile_value(description_lines: list[str], prefix: str) -> str | None:
    for line in description_lines:
        if line.startswith(prefix):
            return line.split(":", 1)[-1].strip()
    return None


def build_company_fact_rows(state: dict[str, Any]) -> list[list[Any]]:
    company = state.get("company_profile", {})
    description_lines = clean_company_description(company.get("description"))

    rows = [
        ["기업명", company.get("name", "-")],
        ["산업 분류", company.get("industry", "-")],
        ["기업 규모/구분", company.get("size", "-")],
    ]

    for label, prefix in [
        ("주소", "주소:"),
        ("홈페이지", "홈페이지:"),
        ("업종코드", "업종코드:"),
        ("설립일", "설립일:"),
        ("결산월", "결산월:"),
    ]:
        value = extract_profile_value(description_lines, prefix)
        if value:
            rows.append([label, value])

    return rows


def infer_source_usage(document: dict[str, Any]) -> str:
    title = str(document.get("title") or "")
    document_type = str(document.get("document_type") or "")
    lowered = title.lower()

    if document_type == "opendart_company_overview":
        return "기업 식별, 상장구분, 업종코드 등 기본 프로필 확인"
    if "sustainability" in lowered or "지속가능" in title:
        return "ESG, 환경, 자원순환, AI 윤리 관련 AX 후보 도출"
    if "business" in lowered or "사업" in title:
        return "사업 영역과 고객 접점 기반 후보 도출"
    if "company" in lowered or "기업" in title or "회사" in title:
        return "경영원칙, 고객 가치, 보안·준법 관련 후보 도출"
    return "업무 후보 발굴 및 RAG 근거 확인"


def build_source_overview_rows(state: dict[str, Any]) -> list[list[Any]]:
    rows = []
    official_url_index = 0

    for document in state.get("documents", []):
        if document.get("document_type") == "official_url":
            official_url_index += 1
            label = f"[공식URL-{official_url_index}]"
        else:
            label = source_label_for_document(document, official_url_index + 1)

        rows.append(
            [
                label,
                document.get("title", "-"),
                document.get("document_type", "-"),
                infer_source_usage(document),
            ]
        )

    return rows


def build_ax_interpretation_rows(state: dict[str, Any]) -> list[list[Any]]:
    rows = []
    seen = set()

    for item in state.get("priority_ranking", {}).get("items", [])[:5]:
        process_name = item.get("process_name") or "-"
        if process_name in seen:
            continue
        seen.add(process_name)
        rows.append(
            [
                process_name,
                item.get("candidate_agent_name", "-"),
                item.get("suitability_rationale") or item.get("reason") or "Discovery Agent 근거 기반 후보",
            ]
        )

    return rows


def summarize_evidence(items: list[dict[str, Any]], limit: int = 3) -> str:
    selected = items[:limit]
    if not selected:
        return "현재 연결된 근거 자료가 부족하여 추가 자료 수집이 필요하다."

    sentences = []
    for item in selected:
        title = item.get("title", "근거 문서")
        summary = " ".join(str(item.get("summary") or "").split())[:180]
        label = item.get("citation_label", "")
        if summary:
            sentences.append(f"{title} 요약: {summary} {label}")
        else:
            sentences.append(f"{title}를 근거 자료로 활용했다. {label}")
    return " ".join(sentences)


def build_process_rows(state: dict[str, Any]) -> list[list[Any]]:
    rows = []
    for process in state.get("business_processes", []):
        rows.append([
            process.get("name"),
            process.get("target_user"),
            process.get("candidate_agent_name"),
            process.get("expected_effect"),
            process.get("data_accessibility"),
            process.get("risk_score"),
        ])
    return rows


def build_candidate_rows(state: dict[str, Any]) -> list[list[Any]]:
    rows = []
    for item in state.get("priority_ranking", {}).get("items", []):
        rows.append([
            item.get("rank"),
            item.get("candidate_agent_name"),
            item.get("target_user"),
            item.get("base_score", "-"),
            item.get("discovery_bonus", "-"),
            item.get("final_score"),
            percent(item.get("saving_rate")),
            item.get("status"),
        ])
    return rows


def build_roi_rows(state: dict[str, Any]) -> list[list[Any]]:
    rows = []
    for item in state.get("roi_cost", {}).get("items", []):
        rows.append([
            item.get("process_name"),
            item.get("candidate_agent_name"),
            money(item.get("monthly_current_cost")),
            money(item.get("monthly_expected_cost")),
            money(item.get("monthly_saving")),
            percent(item.get("saving_rate")),
        ])
    return rows


def build_risk_rows(state: dict[str, Any]) -> list[list[Any]]:
    rows = []
    for item in state.get("risk_governance", {}).get("items", []):
        rows.append([
            item.get("process_name"),
            item.get("candidate_agent_name"),
            item.get("risk_score"),
            item.get("risk_level"),
            ", ".join(item.get("flags", [])),
        ])
    return rows


def build_poc_milestone_rows(state: dict[str, Any]) -> list[list[Any]]:
    rows = []
    for item in state.get("poc_plan", {}).get("poc_plan", {}).get("milestones", []):
        rows.append([
            item.get("phase"),
            item.get("period"),
            item.get("owner"),
            "\n".join(item.get("tasks", [])),
            item.get("deliverable"),
        ])
    return rows


def build_poc_kpi_rows(state: dict[str, Any]) -> list[list[Any]]:
    rows = []
    for item in state.get("poc_plan", {}).get("kpis", []):
        rows.append([item.get("kpi"), item.get("target"), item.get("measurement")])
    return rows


def build_review_rows(state: dict[str, Any]) -> list[list[Any]]:
    review = state.get("human_review", {}) or {}
    if not review:
        return []
    return [
        ["검토자", review.get("reviewer_name", "-")],
        ["결정", review.get("decision", "-")],
        ["검토 채널", review.get("review_channel", "workflow")],
        ["검토 의견", review.get("comment", "-")],
    ]


def build_top_candidate_details(state: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    details = []
    for item in state.get("priority_ranking", {}).get("items", [])[:limit]:
        details.append({
            "rank": item.get("rank"),
            "process_name": item.get("process_name"),
            "candidate_agent_name": item.get("candidate_agent_name"),
            "target_user": item.get("target_user"),
            "status": item.get("status"),
            "base_score": item.get("base_score"),
            "discovery_bonus": item.get("discovery_bonus"),
            "final_score": item.get("final_score"),
            "saving_rate": percent(item.get("saving_rate")),
            "monthly_saving": money(item.get("monthly_saving")),
            "problem": item.get("problem"),
            "reason": item.get("reason"),
            "suitability_rationale": item.get("suitability_rationale"),
            "score_rationale": item.get("score_rationale", {}),
            "risk_flags": item.get("risk_flags", []),
            "discovery_metadata": item.get("discovery_metadata", {}),
        })
    return details


def build_executive_summary(state: dict[str, Any]) -> dict[str, Any]:
    company = state.get("company_profile", {})
    ranking = state.get("priority_ranking", {})
    roi_summary = state.get("roi_cost", {}).get("summary", {})
    risk_summary = state.get("risk_governance", {}).get("summary", {})
    top_candidate = ranking.get("summary", {}).get("top_candidate") or {}
    review = state.get("human_review", {}) or {}

    return {
        "company_name": company.get("name", ""),
        "industry": company.get("industry", ""),
        "process_count": len(state.get("business_processes", [])),
        "document_count": len(state.get("documents", [])),
        "evidence_count": len(state.get("evidence_items", [])),
        "used_source_count": len(state.get("used_sources", [])),
        "top_agent": top_candidate.get("candidate_agent_name", ""),
        "top_process": top_candidate.get("process_name", ""),
        "top_score": top_candidate.get("final_score", ""),
        "top_saving_rate": percent(top_candidate.get("saving_rate")),
        "top_monthly_saving": money(top_candidate.get("monthly_saving")),
        "total_monthly_saving": money(roi_summary.get("total_saving")),
        "total_saving_rate": percent(roi_summary.get("total_saving_rate")),
        "recommended_count": ranking.get("summary", {}).get("recommended_count", 0),
        "review_required_count": ranking.get("summary", {}).get("review_required_count", 0),
        "high_risk_count": risk_summary.get("high_risk_count", 0),
        "human_decision": review.get("decision", "not_reviewed"),
        "reviewer_name": review.get("reviewer_name", "-"),
    }


def build_report_data(state: dict[str, Any]) -> dict[str, Any]:
    company = state.get("company_profile", {})
    evidence_items = state.get("evidence_items", [])
    used_sources = state.get("used_sources", [])
    roi_summary = state.get("roi_cost", {}).get("summary", {})
    ranking = state.get("priority_ranking", {})
    top_candidate = ranking.get("summary", {}).get("top_candidate") or {}
    poc_plan = state.get("poc_plan", {})

    process_evidence = evidence_for(evidence_items, "business_process_analysis")
    report_evidence = evidence_for(evidence_items, "report_generation", limit=10)

    report_requirements = state.get("report_requirements", {})
    title = report_requirements.get("title", "AX 전환 업무 프로세스 진단 및 AI Agent 도입 우선순위 보고서")
    author = report_requirements.get("author", "")
    date_value = report_requirements.get("date", str(date.today()))
    report_status = report_requirements.get("status", "draft")

    return {
        "title": title,
        "author": author,
        "date": date_value,
        "status": report_status,
        "company_name": company.get("name", ""),
        "mvp_agent": top_candidate.get("candidate_agent_name") or "AX Delivery Planner",
        "executive_summary": build_executive_summary(state),
        "top_candidates": build_top_candidate_details(state, limit=5),
        "poc_delivery_plan": poc_plan,
        "sections": [
            {
                "heading": "1. 분석 목적 및 범위",
                "blocks": [
                    {
                        "type": "paragraph",
                        "text": (
                            f"본 보고서는 {company.get('name', '분석 대상 기업')}의 공식자료, 업무 후보, RAG 근거를 기반으로 "
                            f"AI Agent 도입 가능성이 높은 업무를 선별하고 PoC 우선순위를 제안하기 위해 작성되었다. "
                            f"분석에는 업무 프로세스 {len(state.get('business_processes', []))}개, 문서 근거 {len(evidence_items)}개가 사용되었다. "
                            f"{citations(report_evidence)}"
                        ),
                    },
                    {
                        "type": "paragraph",
                        "text": "본 보고서는 회사 공식 출처와 업로드 문서를 RAG로 연결하고, Discovery Agent가 생성한 적합성 근거와 Python 기반 점수 계산을 결합해 작성된다.",
                    },
                ],
            },
            {
                "heading": "2. 기업 및 산업 특성 분석",
                "blocks": [
                    {
                        "type": "paragraph",
                        "text": (
                            f"분석 대상 기업은 {company.get('name', '분석 대상 기업')}이며, "
                            f"산업 분류는 {company.get('industry', '확인 필요')}, 기업 구분은 {company.get('size', '확인 필요')}로 정리하였다. "
                            "본 장은 원문 웹페이지 내용을 그대로 요약하지 않고, AX 후보 도출에 필요한 기업 식별 정보와 공식 출처 활용 목적만 정리한다."
                        ),
                    },
                    {
                        "type": "table",
                        "headers": ["항목", "내용"],
                        "rows": build_company_fact_rows(state),
                        "font_size": 8,
                    },
                    {
                        "type": "paragraph",
                        "text": (
                            "공식자료는 기업의 세부 사업 내용을 장문으로 재현하기보다, AI Agent 후보를 도출하기 위한 분석 기준으로 사용하였다. "
                            "특히 고객지원, ESG·환경관리, 지식자산 보호, AI 윤리·개인정보보호처럼 공식자료에서 반복적으로 확인되는 경영·운영 이슈를 AX 후보군과 연결하였다."
                        ),
                    },
                    {
                        "type": "table",
                        "headers": ["출처", "문서명", "문서 유형", "보고서 활용 목적"],
                        "rows": build_source_overview_rows(state),
                        "font_size": 7,
                    },
                    {
                        "type": "table",
                        "headers": ["AX 해석 포인트", "후보 Agent", "연결 근거"],
                        "rows": build_ax_interpretation_rows(state),
                        "font_size": 7,
                    },
                ],
            },
            {
                "heading": "3. 업무 프로세스 및 데이터 현황",
                "blocks": [
                    {
                        "type": "paragraph",
                        "text": (
                            "업무 프로세스 분석은 DB에 등록된 부서별 업무, 대상 사용자, 문제 정의, 현재 workflow, "
                            f"데이터 접근성, 위험도 점수를 기반으로 수행되었다. {citations(process_evidence)}"
                        ),
                    },
                    {
                        "type": "table",
                        "headers": ["업무명", "대상 사용자", "후보 Agent", "기대효과", "데이터 접근성", "위험도"],
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
                        "text": "우선순위는 기대효과, 데이터 접근성, 반복성, 구현 용이성, 현업 수용성, 보안·거버넌스 위험, 구현 비용을 기준으로 계산하였다. 여기에 Discovery Agent가 생성한 공식자료 기반 적합성 근거를 bonus로 반영하였다.",
                    },
                    {
                        "type": "table",
                        "headers": ["순위", "후보 Agent", "대상 사용자", "기본점수", "근거보정", "최종점수", "절감률", "상태"],
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
                            f"예상 절감액은 {money(roi_summary.get('total_saving'))}, 절감률은 {percent(roi_summary.get('total_saving_rate'))}로 계산되었다."
                        ),
                    },
                    {
                        "type": "table",
                        "headers": ["업무", "후보 Agent", "현재 비용", "예상 비용", "절감액", "절감률"],
                        "rows": build_roi_rows(state),
                        "font_size": 7,
                    },
                ],
            },
            {
                "heading": "6. 보안 및 Governance 위험 분석",
                "blocks": [
                    {"type": "paragraph", "text": "위험 분석은 업무별 보안등급, 민감 키워드, 데이터 접근성, RAG로 검색된 문서의 민감정보 여부를 기준으로 수행되었다."},
                    {
                        "type": "table",
                        "headers": ["업무", "후보 Agent", "위험점수", "위험등급", "위험 플래그"],
                        "rows": build_risk_rows(state),
                        "font_size": 7,
                    },
                ],
            },
            {
                "heading": "7. PoC 실행계획",
                "blocks": [
                    {
                        "type": "paragraph",
                        "text": (
                            f"최상위 후보는 {top_candidate.get('candidate_agent_name', '확인 필요')}이며, 최종 점수는 {top_candidate.get('final_score', 'N/A')}이다. "
                            f"선정 사유는 다음과 같다: {top_candidate.get('reason', '추가 분석 필요')}"
                        ),
                    },
                    {
                        "type": "table",
                        "headers": ["단계", "기간", "Owner", "주요 작업", "산출물"],
                        "rows": build_poc_milestone_rows(state),
                        "font_size": 7,
                    },
                    {
                        "type": "table",
                        "headers": ["KPI", "목표", "측정 방식"],
                        "rows": build_poc_kpi_rows(state),
                        "font_size": 7,
                    },
                ],
            },
            {
                "heading": "8. Human Review 및 의사결정 기록",
                "blocks": [
                    {"type": "paragraph", "text": "PoC 착수 여부는 Agent 추천 결과만으로 확정하지 않고, Human Review 기록을 기준으로 최종 판단한다."},
                    {
                        "type": "table",
                        "headers": ["항목", "내용"],
                        "rows": build_review_rows(state),
                        "font_size": 8,
                    },
                ],
            },
        ],
        "references": used_sources,
    }
