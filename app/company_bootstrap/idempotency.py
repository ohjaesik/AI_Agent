# app/company_bootstrap/idempotency.py

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.company_bootstrap.dart_client import DartCompany
from app.company_bootstrap.service import (
    build_company_description,
    build_discovery_metadata,
    infer_industry,
    infer_size,
)
from app.company_bootstrap.url_loader import OfficialUrlDocument, sanitize_text
from app.db.migrate_discovery_metadata import ensure_discovery_metadata_column
from app.db.models import AnalysisProject, BusinessProcess, Company, Department, EnterpriseSystem, ProcessDocument


def safe_text(value: object, max_chars: int | None = None) -> str:
    text = sanitize_text(str(value or ""))
    if max_chars is not None:
        return text[:max_chars]
    return text


def get_or_update_company(
    db: Session,
    company_name: str,
    combined_text: str,
    dart_company: DartCompany | None = None,
) -> tuple[Company, bool]:
    company = db.execute(
        select(Company).where(Company.name == company_name).order_by(Company.id.asc())
    ).scalars().first()
    created = company is None

    if company is None:
        company = Company(name=company_name, industry="", size="")
        db.add(company)

    company.industry = infer_industry(combined_text, dart_company=dart_company)
    company.size = infer_size(dart_company=dart_company)
    company.description = safe_text(
        build_company_description(
            company_name=company_name,
            combined_text=combined_text,
            dart_company=dart_company,
        )
    )

    db.commit()
    db.refresh(company)
    return company, created


def get_or_create_departments(db: Session, company_id: int) -> tuple[dict[str, Department], int]:
    specs = [
        ("AX전략/기획", "AX 과제 발굴, PoC 기획, 성과관리", "공식자료 기반 업무 후보 구체화 필요"),
        ("IT/데이터", "시스템 연동, 데이터 접근권한, RAG/Agent 운영", "데이터 품질과 권한 관리 필요"),
        ("운영/생산", "핵심 운영 프로세스 수행 및 현장 개선", "반복 업무와 문서 의존 업무 자동화 필요"),
        ("영업/고객", "고객 대응, 제안, 계약, 문의 처리", "문의 대응과 자료 검색 자동화 필요"),
        ("경영지원", "보고, 회의, 규정, 내부 지원", "보고서·회의록·규정 검색 자동화 필요"),
    ]
    existing = {
        item.name: item
        for item in db.execute(select(Department).where(Department.company_id == company_id)).scalars().all()
    }
    created_count = 0

    for name, role, pain in specs:
        row = existing.get(name)
        if row is None:
            row = Department(company_id=company_id, name=name)
            db.add(row)
            existing[name] = row
            created_count += 1
        row.role = role
        row.main_pain_points = pain

    db.commit()
    for row in existing.values():
        db.refresh(row)

    return existing, created_count


def get_or_create_systems(db: Session, company_id: int) -> tuple[list[EnterpriseSystem], int]:
    specs = [
        ("공식자료/RAG 문서 저장소", "knowledge_base", "IT/데이터", 4, True, "공식 URL, 공시, 업로드 문서를 검색 가능한 지식베이스로 활용"),
        ("업무 프로세스 분석 DB", "analysis_db", "AX전략/기획", 4, True, "AX 후보 업무와 평가 결과 저장"),
        ("Human Review 로그", "governance_log", "경영지원", 3, True, "의사결정 근거와 승인 이력 저장"),
    ]
    existing = {
        item.name: item
        for item in db.execute(select(EnterpriseSystem).where(EnterpriseSystem.company_id == company_id)).scalars().all()
    }
    rows: list[EnterpriseSystem] = []
    created_count = 0

    for name, system_type, owner, level, api_available, description in specs:
        row = existing.get(name)
        if row is None:
            row = EnterpriseSystem(company_id=company_id, name=name, system_type=system_type)
            db.add(row)
            existing[name] = row
            created_count += 1
        row.system_type = system_type
        row.owner_department = owner
        row.data_access_level = level
        row.api_available = api_available
        row.description = description
        rows.append(row)

    db.commit()
    for row in rows:
        db.refresh(row)

    return rows, created_count


def find_official_url_document(db: Session, company_id: int, url: str) -> ProcessDocument | None:
    row = db.execute(
        select(ProcessDocument).where(
            ProcessDocument.company_id == company_id,
            ProcessDocument.document_type == "official_url",
            ProcessDocument.source_url == url,
        )
    ).scalars().first()
    if row is not None:
        return row

    prefix = f"공식 URL: {url}\n"
    rows = db.execute(
        select(ProcessDocument).where(
            ProcessDocument.company_id == company_id,
            ProcessDocument.document_type == "official_url",
        )
    ).scalars().all()

    for row in rows:
        if row.content.startswith(prefix):
            return row
    return None


def upsert_source_documents(
    db: Session,
    company_id: int,
    official_docs: list[OfficialUrlDocument],
    dart_company: DartCompany | None,
) -> tuple[list[ProcessDocument], int, int]:
    rows: list[ProcessDocument] = []
    created_count = 0
    updated_count = 0

    if dart_company is not None:
        title = f"{dart_company.corp_name} OpenDART 기업개황"
        source_url = f"opendart://company/{dart_company.corp_code}"
        row = db.execute(
            select(ProcessDocument).where(
                ProcessDocument.company_id == company_id,
                ProcessDocument.document_type == "opendart_company_overview",
                ProcessDocument.source_url == source_url,
            )
        ).scalars().first()
        if row is None:
            row = ProcessDocument(
                company_id=company_id,
                process_id=None,
                title=title,
                document_type="opendart_company_overview",
                content="",
                department="공식공시",
                security_level="public_official",
                contains_sensitive_info=False,
                source_url=source_url,
                allowed_roles=["viewer", "analyst", "manager", "admin"],
            )
            db.add(row)
            created_count += 1
        else:
            updated_count += 1
        row.title = safe_text(title, 200)
        row.content = safe_text(dart_company.to_document_content())
        row.department = "공식공시"
        row.security_level = "public_official"
        row.contains_sensitive_info = False
        row.source_url = source_url
        row.allowed_roles = ["viewer", "analyst", "manager", "admin"]
        rows.append(row)

    for doc in official_docs:
        content = safe_text(f"공식 URL: {doc.url}\n문서 제목: {doc.title}\n\n{doc.content}")
        row = find_official_url_document(db, company_id=company_id, url=doc.url)
        if row is None:
            row = ProcessDocument(
                company_id=company_id,
                process_id=None,
                title=safe_text(doc.title, 200),
                document_type="official_url",
                content=content,
                department="공식웹사이트",
                security_level="public_official",
                contains_sensitive_info=False,
                source_url=doc.url,
                allowed_roles=["viewer", "analyst", "manager", "admin"],
            )
            db.add(row)
            created_count += 1
        else:
            updated_count += 1
            row.title = safe_text(doc.title, 200)
            row.content = content
            row.department = "공식웹사이트"
            row.security_level = "public_official"
            row.contains_sensitive_info = False
            row.source_url = doc.url
            row.allowed_roles = ["viewer", "analyst", "manager", "admin"]
        rows.append(row)

    db.commit()
    for row in rows:
        db.refresh(row)

    return rows, created_count, updated_count


def upsert_business_processes(
    db: Session,
    company_id: int,
    departments: dict[str, Department],
    process_specs: list[dict],
) -> tuple[list[BusinessProcess], int, int]:
    ensure_discovery_metadata_column()
    rows: list[BusinessProcess] = []
    created_count = 0
    updated_count = 0

    existing = {
        (item.name, item.candidate_agent_name or ""): item
        for item in db.execute(select(BusinessProcess).where(BusinessProcess.company_id == company_id)).scalars().all()
    }

    for spec in process_specs:
        department = departments.get(spec.get("department")) or departments["AX전략/기획"]
        key = (spec["name"], spec.get("candidate_agent_name") or "")
        row = existing.get(key)
        if row is None:
            row = BusinessProcess(company_id=company_id, department_id=department.id, name=spec["name"], target_user=spec["target_user"], problem=spec["problem"])
            db.add(row)
            created_count += 1
        else:
            updated_count += 1

        discovery_note = ""
        if spec.get("discovery_mode"):
            discovery_note = f"\n\n생성방식: {spec.get('discovery_mode')}"
        if spec.get("discovery_warning"):
            discovery_note += f"\n주의: {spec.get('discovery_warning')}"

        row.department_id = department.id
        row.target_user = spec["target_user"]
        row.problem = spec["problem"]
        row.current_workflow = f"{spec.get('current_workflow') or ''}{discovery_note}".strip()
        row.weekly_hours = spec["weekly_hours"]
        row.hourly_cost = 40000
        row.expected_effect = spec["expected_effect"]
        row.repeatability = spec["repeatability"]
        row.document_dependency = spec["document_dependency"]
        row.decision_complexity = spec["decision_complexity"]
        row.data_accessibility = spec["data_accessibility"]
        row.tech_feasibility = spec["tech_feasibility"]
        row.user_acceptance = spec["user_acceptance"]
        row.risk_score = spec["risk_score"]
        row.implementation_cost_score = spec["implementation_cost_score"]
        row.security_level = spec.get("security_level", "internal")
        row.candidate_agent_name = spec["candidate_agent_name"]
        row.discovery_metadata = build_discovery_metadata(spec)
        rows.append(row)

    db.commit()
    for row in rows:
        db.refresh(row)

    return rows, created_count, updated_count


def get_or_create_project(db: Session, company_id: int, company_name: str) -> tuple[AnalysisProject, bool]:
    title = f"{company_name} 공식자료 기반 AX 전환 진단"
    project = db.execute(
        select(AnalysisProject).where(
            AnalysisProject.company_id == company_id,
            AnalysisProject.title == title,
        )
    ).scalars().first()
    created = project is None

    if project is None:
        project = AnalysisProject(company_id=company_id, title=title, status="created")
        db.add(project)
    else:
        project.status = "updated"

    db.commit()
    db.refresh(project)
    return project, created


def get_or_create_analysis_project(db: Session, company_id: int, company_name: str) -> tuple[AnalysisProject, bool]:
    """Backward-compatible alias for bootstrap nodes that create the analysis project."""
    return get_or_create_project(db=db, company_id=company_id, company_name=company_name)
