# app/db/crud.py

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
    return db.get(Company, company_id)


def get_company_profile(db: Session, company_id: int) -> dict[str, Any]:
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
    return db.get(AnalysisProject, project_id)


def get_project_payload(db: Session, project_id: int) -> dict[str, Any]:
    project = db.get(AnalysisProject, project_id)

    if project is None:
        raise ValueError(f"AnalysisProject not found: {project_id}")

    return project_to_payload(project)


def project_to_payload(project: AnalysisProject) -> dict[str, Any]:
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
    stmt = delete(DocumentChunk).where(DocumentChunk.company_id == company_id)
    result = db.execute(stmt)
    db.commit()
    return result.rowcount or 0
