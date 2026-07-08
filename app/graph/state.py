# app/graph/state.py

from __future__ import annotations

import json
from typing import Annotated, Any, TypedDict


def merge_unique_dicts(left: list[dict[str, Any]] | None, right: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in (left or []) + (right or []):
        try:
            key = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
        except TypeError:
            key = str(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)

    return result


def merge_unique_strings(left: list[str] | None, right: list[str] | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for item in (left or []) + (right or []):
        if item in seen:
            continue
        seen.add(item)
        result.append(item)

    return result


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
    compliance_assessment: dict[str, Any]
    priority_ranking: dict[str, Any]

    # Human Review
    human_review: dict[str, Any]

    # PoC / Report
    poc_plan: dict[str, Any]
    report_outline: dict[str, Any]
    report_data: dict[str, Any]
    report_docx_path: str

    # Logs. Reducers are required because several analysis agents run in parallel.
    audit_logs: Annotated[list[dict[str, Any]], merge_unique_dicts]
    errors: Annotated[list[str], merge_unique_strings]
