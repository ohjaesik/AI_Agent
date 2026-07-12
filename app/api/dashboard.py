"""홈 대시보드 summary payload builder.

프론트 홈 화면은 demo 숫자를 직접 만들지 않고 `/dashboard/summary` 응답만 믿는다.
이 모듈은 그 응답에 필요한 DB count와 최근 workflow_state 요약을 한곳에서 만든다.
FastAPI route 함수에서 분리해두면 화면 요구사항이 바뀌어도 API 라우팅 코드는 작게
유지할 수 있다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.crud import resolve_project_selection
from app.db.models import (
    AnalysisProject,
    AuditLog,
    BusinessProcess,
    Company,
    Department,
    DocumentChunk,
    EnterpriseSystem,
    ProcessDocument,
)
from app.main import DEFAULT_STATE_OUTPUT_PATH
from app.security.access_control import AccessContext


WORKFLOW_STATE_PATH = Path(DEFAULT_STATE_OUTPUT_PATH)


def _count_rows(db: Session, model: type[Any], *conditions: Any) -> int:
    """지정 table에서 조건에 맞는 row 수를 계산한다."""

    stmt = select(func.count()).select_from(model)
    for condition in conditions:
        stmt = stmt.where(condition)
    return int(db.scalar(stmt) or 0)


def _load_workflow_state_snapshot(path: Path = WORKFLOW_STATE_PATH) -> dict[str, Any]:
    """최근 Supervisor 실행 결과 JSON을 읽는다.

    파일이 아직 없거나 깨진 경우에도 대시보드 전체가 실패하지 않도록 빈 dict를 반환한다.
    DB 현황은 계속 표시하고, 최근 분석 결과 영역만 "분석 전"으로 남기는 의도다.
    """

    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _extract_workflow_summary(snapshot: dict[str, Any], path: Path = WORKFLOW_STATE_PATH) -> dict[str, Any]:
    """workflow_state 전체 중 홈 화면에 필요한 trace만 추린다."""

    priority_items = (snapshot.get("priority_ranking") or {}).get("items") or []
    if not priority_items:
        priority_items = snapshot.get("top_candidates") or []

    report_data = snapshot.get("report_data") or {}
    citation_validation = snapshot.get("citation_validation") or report_data.get("citation_validation") or {}
    total_cost_summary = snapshot.get("total_cost_summary") or {}

    return {
        "state_file_path": str(path) if path.exists() else None,
        "report_docx_path": snapshot.get("report_docx_path"),
        "report_status": (report_data.get("generation") or {}).get("status"),
        "top_candidate_count": len(priority_items),
        "top_candidates": priority_items[:5],
        "agent_tool_call_count": len(snapshot.get("agent_tool_calls") or []),
        "agent_model_decision_count": len(snapshot.get("agent_model_decisions") or []),
        "supervisor_delegation_count": len(snapshot.get("agent_supervisor_delegations") or []),
        "autonomy_loop_decision_count": len(snapshot.get("agent_autonomy_loop_decisions") or []),
        "error_count": len(snapshot.get("errors") or []),
        "citation_validated": citation_validation.get("valid"),
        "citation_issue_count": len(citation_validation.get("issues") or []),
        "total_cost_summary": total_cost_summary,
        "estimated_total_cost_usd": total_cost_summary.get("estimated_total_cost_usd"),
    }


def _company_payload(company: Company | None) -> dict[str, Any] | None:
    """Company ORM 객체를 프론트가 바로 쓰기 쉬운 JSON dict로 바꾼다."""

    if company is None:
        return None
    return {
        "id": company.id,
        "name": company.name,
        "industry": company.industry,
        "size": company.size,
        "description": company.description,
    }


def _project_payload(project: AnalysisProject | None) -> dict[str, Any] | None:
    """AnalysisProject ORM 객체를 홈 대시보드 표시용 JSON dict로 바꾼다."""

    if project is None:
        return None
    return {
        "id": project.id,
        "company_id": project.company_id,
        "title": project.title,
        "status": project.status,
        "created_at": project.created_at.isoformat() if project.created_at else None,
    }


def _build_counts(db: Session, company_id: int, project_id: int) -> dict[str, int]:
    """홈 대시보드 숫자 카드에 표시할 실제 DB count를 모은다."""

    return {
        "departments": _count_rows(db, Department, Department.company_id == company_id),
        "enterprise_systems": _count_rows(db, EnterpriseSystem, EnterpriseSystem.company_id == company_id),
        "business_processes": _count_rows(db, BusinessProcess, BusinessProcess.company_id == company_id),
        "documents": _count_rows(db, ProcessDocument, ProcessDocument.company_id == company_id),
        "document_chunks": _count_rows(db, DocumentChunk, DocumentChunk.company_id == company_id),
        "sensitive_documents": _count_rows(
            db,
            ProcessDocument,
            ProcessDocument.company_id == company_id,
            ProcessDocument.contains_sensitive_info.is_(True),
        ),
        "audit_logs": _count_rows(db, AuditLog, AuditLog.project_id == project_id),
    }


def build_dashboard_summary(
    db: Session,
    access: AccessContext,
    company_id: int | None = None,
    project_id: int | None = None,
) -> dict[str, Any]:
    """DB와 최근 workflow_state를 합쳐 `/dashboard/summary` 응답을 만든다."""

    resolved = resolve_project_selection(db=db, project_id=project_id, company_id=company_id)
    resolved_company_id = resolved["company_id"]
    resolved_project_id = resolved["project_id"]

    company = db.get(Company, resolved_company_id)
    project = db.get(AnalysisProject, resolved_project_id)
    workflow_summary = _extract_workflow_summary(_load_workflow_state_snapshot())

    return {
        "status": "ok",
        "access": {"user_id": access.user_id, "role": access.role},
        "company": _company_payload(company),
        "project": _project_payload(project),
        "counts": _build_counts(db, resolved_company_id, resolved_project_id),
        "workflow": workflow_summary,
    }
