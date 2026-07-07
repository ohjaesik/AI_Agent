# app/graph/state.py

from __future__ import annotations

from typing import Any, TypedDict


class AXPlannerState(TypedDict, total=False):
    project_id: int
    company_id: int

    # 사용자 요청 / 보고서 요구사항
    user_request: str
    report_requirements: dict[str, Any]

    # DB에서 로드한 데이터
    project: dict[str, Any]
    company_profile: dict[str, Any]
    departments: list[dict[str, Any]]
    business_processes: list[dict[str, Any]]
    systems: list[dict[str, Any]]
    documents: list[dict[str, Any]]

    # RAG / Evidence
    retrieved_contexts: dict[str, list[dict[str, Any]]]
    evidence_items: list[dict[str, Any]]
    used_sources: list[dict[str, Any]]

    # Agent / Tool 분석 결과
    process_analysis: dict[str, Any]
    data_readiness: dict[str, Any]
    automation_feasibility: dict[str, Any]
    roi_cost: dict[str, Any]
    risk_governance: dict[str, Any]
    priority_ranking: dict[str, Any]

    # Human Review
    human_review: dict[str, Any]

    # PoC / Report
    poc_plan: dict[str, Any]
    report_outline: dict[str, Any]
    report_data: dict[str, Any]
    report_docx_path: str

    # Logs
    audit_logs: list[dict[str, Any]]
    errors: list[str]