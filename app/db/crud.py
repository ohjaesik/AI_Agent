# app/db/crud.py

"""DB 읽기/쓰기 helper 모음.

project/company/process/document/analysis result/human review/audit log를 저장하거나
조회하는 함수를 제공한다.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import (
    AnalysisProject,
    AnalysisResult,
    AuditLog,
    BusinessProcess,
    Company,
    Department,
    DocumentChunk,
    EnterpriseSystem,
    HumanReview,
    ProcessDocument,
)


def get_company(db: Session, company_id: int) -> Company | None:
    """company_id로 Company ORM 객체를 조회한다."""
    return db.get(Company, company_id)


def get_company_profile(db: Session, company_id: int) -> dict[str, Any]:
    """Company row를 LangGraph state에 넣을 profile dict로 변환한다."""
    company = db.get(Company, company_id)

    if company is None:
        raise ValueError(f"Company not found: {company_id}")

    return {
        "id": company.id,
        "name": company.name,
        "industry": company.industry,
        "size": company.size,
        "description": company.description,
    }


def get_departments(db: Session, company_id: int) -> list[dict[str, Any]]:
    """해당 회사의 부서 목록을 분석 node가 소비하는 dict 목록으로 조회한다."""
    stmt = (
        select(Department)
        .where(Department.company_id == company_id)
        .order_by(Department.id)
    )
    departments = db.execute(stmt).scalars().all()

    return [
        {
            "id": item.id,
            "company_id": item.company_id,
            "name": item.name,
            "role": item.role,
            "main_pain_points": item.main_pain_points,
        }
        for item in departments
    ]


def get_systems(db: Session, company_id: int) -> list[dict[str, Any]]:
    """해당 회사의 enterprise system 목록을 분석용 dict 목록으로 조회한다."""
    stmt = (
        select(EnterpriseSystem)
        .where(EnterpriseSystem.company_id == company_id)
        .order_by(EnterpriseSystem.id)
    )
    systems = db.execute(stmt).scalars().all()

    return [
        {
            "id": item.id,
            "company_id": item.company_id,
            "name": item.name,
            "system_type": item.system_type,
            "owner_department": item.owner_department,
            "data_access_level": item.data_access_level,
            "api_available": item.api_available,
            "description": item.description,
        }
        for item in systems
    ]


def get_business_processes(db: Session, company_id: int) -> list[dict[str, Any]]:
    """AX 후보 업무/프로세스 row를 scoring과 RAG가 사용할 payload로 조회한다."""
    stmt = (
        select(BusinessProcess)
        .where(BusinessProcess.company_id == company_id)
        .order_by(BusinessProcess.id)
    )
    processes = db.execute(stmt).scalars().all()

    return [
        {
            "id": item.id,
            "company_id": item.company_id,
            "department_id": item.department_id,
            "name": item.name,
            "target_user": item.target_user,
            "problem": item.problem,
            "current_workflow": item.current_workflow,
            "weekly_hours": item.weekly_hours,
            "hourly_cost": item.hourly_cost,
            "expected_effect": item.expected_effect,
            "repeatability": item.repeatability,
            "document_dependency": item.document_dependency,
            "decision_complexity": item.decision_complexity,
            "data_accessibility": item.data_accessibility,
            "tech_feasibility": item.tech_feasibility,
            "user_acceptance": item.user_acceptance,
            "risk_score": item.risk_score,
            "implementation_cost_score": item.implementation_cost_score,
            "security_level": item.security_level,
            "candidate_agent_name": item.candidate_agent_name,
            "discovery_metadata": item.discovery_metadata,
        }
        for item in processes
    ]


def get_process_documents(db: Session, company_id: int) -> list[dict[str, Any]]:
    """회사 문서를 RAG/증거 수집 node가 사용할 metadata 포함 dict 목록으로 조회한다."""
    stmt = (
        select(ProcessDocument)
        .where(ProcessDocument.company_id == company_id)
        .order_by(ProcessDocument.id)
    )
    documents = db.execute(stmt).scalars().all()

    return [
        {
            "id": item.id,
            "company_id": item.company_id,
            "process_id": item.process_id,
            "title": item.title,
            "document_type": item.document_type,
            "content": item.content,
            "department": item.department,
            "security_level": item.security_level,
            "contains_sensitive_info": item.contains_sensitive_info,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }
        for item in documents
    ]


def get_project(db: Session, project_id: int) -> AnalysisProject | None:
    """project_id로 AnalysisProject ORM 객체를 조회한다."""
    return db.get(AnalysisProject, project_id)


def get_project_payload(db: Session, project_id: int) -> dict[str, Any]:
    """AnalysisProject를 찾고 없으면 명확한 오류를 낸 뒤 payload dict로 변환한다."""
    project = db.get(AnalysisProject, project_id)

    if project is None:
        raise ValueError(f"AnalysisProject not found: {project_id}")

    return project_to_payload(project)


def project_to_payload(project: AnalysisProject) -> dict[str, Any]:
    """AnalysisProject ORM 객체를 API/graph 공통 payload로 변환한다."""
    return {
        "id": project.id,
        "company_id": project.company_id,
        "title": project.title,
        "status": project.status,
        "created_at": project.created_at.isoformat() if project.created_at else None,
    }


def get_latest_project(
    db: Session,
    company_id: int | None = None,
) -> dict[str, Any]:
    """회사 필터가 있으면 해당 회사의, 없으면 전체 최신 AnalysisProject를 반환한다."""
    stmt = select(AnalysisProject)

    if company_id is not None:
        stmt = stmt.where(AnalysisProject.company_id == company_id)

    stmt = stmt.order_by(
        AnalysisProject.created_at.desc(),
        AnalysisProject.id.desc(),
    )

    project = db.execute(stmt).scalars().first()

    if project is None:
        if company_id is None:
            raise ValueError("AnalysisProject not found. Run seed first.")
        raise ValueError(f"AnalysisProject not found for company_id={company_id}. Run seed first.")

    return project_to_payload(project)


def resolve_project_selection(
    db: Session,
    project_id: int | None = None,
    company_id: int | None = None,
) -> dict[str, int]:
    """project_id/company_id 입력 조합을 검증하고 실행에 사용할 최종 id 쌍을 결정한다."""
    if project_id is not None:
        project = get_project_payload(db, project_id)

        resolved_company_id = int(project["company_id"])

        if company_id is not None and company_id != resolved_company_id:
            raise ValueError(
                f"project_id={project_id} belongs to company_id={resolved_company_id}, "
                f"but company_id={company_id} was provided."
            )

        return {
            "project_id": int(project["id"]),
            "company_id": resolved_company_id,
        }

    project = get_latest_project(db, company_id=company_id)

    return {
        "project_id": int(project["id"]),
        "company_id": int(project["company_id"]),
    }


def load_project_data(db: Session, project_id: int, company_id: int) -> dict[str, Any]:
    """load_project_data 함수. 외부/DB/파일 입력을 읽어 workflow에서 사용할 구조로 적재한다."""
    project = get_project_payload(db, project_id)

    if int(project["company_id"]) != int(company_id):
        raise ValueError(
            f"project_id={project_id} belongs to company_id={project['company_id']}, "
            f"but company_id={company_id} was provided."
        )

    return {
        "project": project,
        "company_profile": get_company_profile(db, company_id),
        "departments": get_departments(db, company_id),
        "systems": get_systems(db, company_id),
        "business_processes": get_business_processes(db, company_id),
        "documents": get_process_documents(db, company_id),
    }


def save_analysis_result(
    db: Session,
    project_id: int,
    node_name: str,
    result_json: dict[str, Any],
) -> AnalysisResult:
    """save_analysis_result 함수. 분석 결과나 사용자 결정을 DB 또는 파일에 저장한다."""
    row = AnalysisResult(
        project_id=project_id,
        node_name=node_name,
        result_json=result_json,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def save_human_review(
    db: Session,
    project_id: int,
    reviewer_name: str,
    decision: str,
    comment: str | None = None,
    edited_payload: dict[str, Any] | None = None,
) -> HumanReview:
    """save_human_review 함수. 분석 결과나 사용자 결정을 DB 또는 파일에 저장한다."""
    row = HumanReview(
        project_id=project_id,
        reviewer_name=reviewer_name,
        decision=decision,
        comment=comment,
        edited_payload=edited_payload,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def write_audit_log(
    db: Session,
    project_id: int | None,
    node_name: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> AuditLog:
    """write_audit_log 함수. audit log나 결과 payload를 영속 저장소에 기록한다."""
    row = AuditLog(
        project_id=project_id,
        node_name=node_name,
        event_type=event_type,
        payload=payload,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def delete_chunks_by_company(db: Session, company_id: int) -> int:
    """delete_chunks_by_company 함수. 재색인/정리 과정에서 기존 데이터를 안전하게 삭제한다."""
    stmt = delete(DocumentChunk).where(DocumentChunk.company_id == company_id)
    result = db.execute(stmt)
    db.commit()
    return result.rowcount or 0


def delete_seed_data(db: Session) -> None:
    """
    개발 중 seed를 여러 번 실행하기 위한 초기화 함수.
    FK 의존성 때문에 하위 테이블부터 삭제한다.
    """
    db.execute(delete(DocumentChunk))
    db.execute(delete(AuditLog))
    db.execute(delete(HumanReview))
    db.execute(delete(AnalysisResult))
    db.execute(delete(AnalysisProject))
    db.execute(delete(ProcessDocument))
    db.execute(delete(BusinessProcess))
    db.execute(delete(EnterpriseSystem))
    db.execute(delete(Department))
    db.execute(delete(Company))
    db.commit()
