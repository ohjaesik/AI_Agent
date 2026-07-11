# app/company_bootstrap/service.py

"""회사 bootstrap을 서비스 함수 형태로 제공한다.

API layer가 직접 graph 세부 구현을 알 필요 없이 company bootstrap을 호출할 수 있게
입력 정리와 결과 포장을 담당한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.chains.company_process_discovery import discover_company_process_specs
from app.company_bootstrap.dart_client import DartCompany, load_dart_company
from app.company_bootstrap.url_loader import OfficialUrlDocument, load_official_url
from app.db.migrate_discovery_metadata import ensure_discovery_metadata_column
from app.db.models import AnalysisProject, BusinessProcess, Company, Department, EnterpriseSystem, ProcessDocument
from app.ingestion.service import index_single_document
from app.rag.indexer import delete_existing_chunks


@dataclass(frozen=True)
class BootstrapResult:
    """기존 service 기반 bootstrap 결과를 호출자에게 반환하기 위한 값 객체다."""
    company_id: int
    project_id: int | None
    document_ids: list[int]
    process_ids: list[int]
    chunk_count: int
    source_count: int
    warnings: list[str]
    discovery_mode: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """dataclass/value object를 JSON 직렬화 가능한 dict로 변환한다."""
        return {
            "company_id": self.company_id,
            "project_id": self.project_id,
            "document_ids": self.document_ids,
            "process_ids": self.process_ids,
            "chunk_count": self.chunk_count,
            "source_count": self.source_count,
            "warnings": self.warnings,
            "discovery_mode": self.discovery_mode,
        }


def infer_industry(text: str, dart_company: DartCompany | None = None) -> str:
    """infer_industry 함수. 명시 입력이 없을 때 텍스트나 metadata에서 보수적인 추정값을 만든다."""
    if dart_company and dart_company.profile.get("induty_code"):
        return f"공식자료 기반 업종코드 {dart_company.profile.get('induty_code')}"

    lowered = text.lower()
    keyword_map = [
        ("반도체", "반도체/전자 제조업"),
        ("전자", "전자/전기 제조업"),
        ("제조", "제조업"),
        ("manufacturing", "제조업"),
        ("자동차", "자동차/부품 제조업"),
        ("건설", "건설업"),
        ("금융", "금융업"),
        ("소프트웨어", "소프트웨어/IT 서비스업"),
        ("platform", "플랫폼/IT 서비스업"),
        ("바이오", "바이오/헬스케어"),
        ("물류", "물류/유통업"),
        ("유통", "물류/유통업"),
    ]

    for keyword, industry in keyword_map:
        if keyword in lowered:
            return industry

    return "공식자료 기반 산업 분류 필요"


def infer_size(dart_company: DartCompany | None = None) -> str:
    """infer_size 함수. 명시 입력이 없을 때 텍스트나 metadata에서 보수적인 추정값을 만든다."""
    if dart_company is None:
        return "확인 필요"

    corp_cls = dart_company.corp_cls or ""
    if corp_cls == "Y":
        return "유가증권시장 상장사"
    if corp_cls == "K":
        return "코스닥 상장사"
    if corp_cls == "N":
        return "코넥스 상장사"
    if corp_cls == "E":
        return "기타 외감법인"
    return "확인 필요"


def build_company_description(
    company_name: str,
    combined_text: str,
    dart_company: DartCompany | None = None,
) -> str:
    """build_company_description 함수. 입력 state나 domain 객체를 조합해 downstream에서 사용할 구조화된 payload를 만든다."""
    parts = [f"{company_name} 공식자료 기반 AX 분석용 회사 프로필"]

    if dart_company is not None:
        profile = dart_company.profile
        for label, key in [
            ("주소", "adres"),
            ("홈페이지", "hm_url"),
            ("업종코드", "induty_code"),
            ("설립일", "est_dt"),
            ("결산월", "acc_mt"),
        ]:
            value = profile.get(key)
            if value:
                parts.append(f"{label}: {value}")

    return "\n".join(parts)


def create_company(
    db: Session,
    company_name: str,
    combined_text: str,
    dart_company: DartCompany | None = None,
) -> Company:
    """create_company 함수. DB record 또는 domain 객체를 생성하고 필요한 기본값/관계를 함께 설정한다."""
    company = Company(
        name=company_name,
        industry=infer_industry(combined_text, dart_company=dart_company),
        size=infer_size(dart_company=dart_company),
        description=build_company_description(
            company_name=company_name,
            combined_text=combined_text,
            dart_company=dart_company,
        ),
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def create_default_departments(db: Session, company_id: int) -> dict[str, Department]:
    """create_default_departments 함수. DB record 또는 domain 객체를 생성하고 필요한 기본값/관계를 함께 설정한다."""
    specs = [
        ("AX전략/기획", "AX 과제 발굴, PoC 기획, 성과관리", "공식자료 기반 업무 후보 구체화 필요"),
        ("IT/데이터", "시스템 연동, 데이터 접근권한, RAG/Agent 운영", "데이터 품질과 권한 관리 필요"),
        ("운영/생산", "핵심 운영 프로세스 수행 및 현장 개선", "반복 업무와 문서 의존 업무 자동화 필요"),
        ("영업/고객", "고객 대응, 제안, 계약, 문의 처리", "문의 대응과 자료 검색 자동화 필요"),
        ("경영지원", "보고, 회의, 규정, 내부 지원", "보고서·회의록·규정 검색 자동화 필요"),
    ]
    result: dict[str, Department] = {}

    for name, role, pain in specs:
        department = Department(
            company_id=company_id,
            name=name,
            role=role,
            main_pain_points=pain,
        )
        db.add(department)
        result[name] = department

    db.commit()
    for department in result.values():
        db.refresh(department)
    return result


def create_default_systems(db: Session, company_id: int) -> list[EnterpriseSystem]:
    """create_default_systems 함수. DB record 또는 domain 객체를 생성하고 필요한 기본값/관계를 함께 설정한다."""
    specs = [
        ("공식자료/RAG 문서 저장소", "knowledge_base", "IT/데이터", 4, True, "공식 URL, 공시, 업로드 문서를 검색 가능한 지식베이스로 활용"),
        ("업무 프로세스 분석 DB", "analysis_db", "AX전략/기획", 4, True, "AX 후보 업무와 평가 결과 저장"),
        ("Human Review 로그", "governance_log", "경영지원", 3, True, "의사결정 근거와 승인 이력 저장"),
    ]
    rows: list[EnterpriseSystem] = []

    for name, system_type, owner, level, api_available, description in specs:
        row = EnterpriseSystem(
            company_id=company_id,
            name=name,
            system_type=system_type,
            owner_department=owner,
            data_access_level=level,
            api_available=api_available,
            description=description,
        )
        db.add(row)
        rows.append(row)

    db.commit()
    for row in rows:
        db.refresh(row)
    return rows


def contains_any(text: str, keywords: list[str]) -> bool:
    """contains_any 함수. 조건을 검사해 True/False 판단값을 반환한다."""
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def process_spec(
    department: str,
    name: str,
    target_user: str,
    problem: str,
    current_workflow: str,
    candidate_agent_name: str,
    weekly_hours: float,
    expected_effect: int,
    repeatability: int,
    document_dependency: int,
    decision_complexity: int,
    data_accessibility: int,
    tech_feasibility: int,
    user_acceptance: int,
    risk_score: int,
    implementation_cost_score: int,
) -> dict[str, Any]:
    """process_spec 함수. 회사 bootstrap을 서비스 함수 형태로 제공한다. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    return {
        "department": department,
        "name": name,
        "target_user": target_user,
        "problem": problem,
        "current_workflow": current_workflow,
        "candidate_agent_name": candidate_agent_name,
        "weekly_hours": weekly_hours,
        "expected_effect": expected_effect,
        "repeatability": repeatability,
        "document_dependency": document_dependency,
        "decision_complexity": decision_complexity,
        "data_accessibility": data_accessibility,
        "tech_feasibility": tech_feasibility,
        "user_acceptance": user_acceptance,
        "risk_score": risk_score,
        "implementation_cost_score": implementation_cost_score,
    }


def build_process_specs(combined_text: str) -> list[dict[str, Any]]:
    """build_process_specs 함수. 입력 state나 domain 객체를 조합해 downstream에서 사용할 구조화된 payload를 만든다."""
    specs = [
        process_spec(
            "AX전략/기획",
            "공식자료 기반 AX 과제 발굴",
            "AX 기획 담당자",
            "회사 공식자료, 사업영역, 공시, 홈페이지 정보를 수동으로 읽고 AX 후보를 정리해야 한다.",
            "담당자가 공식자료를 수집하고 사업·업무 단서를 수작업으로 요약한다.",
            "공식자료 AX 진단 Agent",
            8.0,
            4,
            4,
            5,
            3,
            4,
            4,
            4,
            3,
            3,
        ),
        process_spec(
            "경영지원",
            "내부/공식 문서 질의응답",
            "기획·지원 부서 담당자",
            "회사소개, 사업영역, 공시, 규정성 문서를 찾고 요약하는 데 시간이 든다.",
            "문서나 웹페이지를 직접 열람하고 필요한 내용을 복사해 정리한다.",
            "공식자료 RAG Q&A Agent",
            10.0,
            4,
            5,
            5,
            2,
            4,
            5,
            4,
            2,
            2,
        ),
        process_spec(
            "경영지원",
            "회의록 및 보고서 초안 작성",
            "기획·관리 담당자",
            "회의 내용과 공식 근거를 결합해 보고서 초안을 작성하는 반복 업무가 많다.",
            "회의 메모와 자료를 사람이 취합해 보고서 초안을 작성한다.",
            "회의록·보고서 Draft Agent",
            6.0,
            4,
            4,
            4,
            3,
            3,
            4,
            4,
            3,
            3,
        ),
    ]

    if contains_any(combined_text, ["제조", "생산", "품질", "공장", "설비", "공정", "manufacturing", "factory"]):
        specs.extend(
            [
                process_spec(
                    "운영/생산",
                    "생산·품질 문서 검색 및 표준작업 지원",
                    "생산·품질 담당자",
                    "제품, 공정, 품질 관련 문서를 찾고 표준작업 기준을 확인하는 시간이 발생한다.",
                    "담당자가 문서함과 기존 보고서를 직접 검색해 기준을 확인한다.",
                    "생산·품질 SOP 질의응답 Agent",
                    12.0,
                    5,
                    5,
                    5,
                    3,
                    4,
                    5,
                    4,
                    3,
                    3,
                ),
                process_spec(
                    "운영/생산",
                    "설비·공정 이슈 이력 분석",
                    "운영·설비 담당자",
                    "설비, 공정, 품질 이슈의 반복 패턴을 사람이 보고서 중심으로 확인해야 한다.",
                    "이슈 보고서와 정비 기록을 수동으로 검토해 원인과 대응을 정리한다.",
                    "설비·공정 이슈 분석 Agent",
                    10.0,
                    4,
                    4,
                    4,
                    4,
                    3,
                    4,
                    3,
                    4,
                    4,
                ),
            ]
        )

    if contains_any(combined_text, ["고객", "문의", "서비스", "영업", "판매", "customer", "sales"]):
        specs.append(
            process_spec(
                "영업/고객",
                "고객 문의 및 제품 자료 응답 지원",
                "영업·고객 대응 담당자",
                "고객 문의에 답변하기 위해 회사소개, 제품, 서비스 자료를 반복적으로 확인해야 한다.",
                "담당자가 공식자료와 내부 문서를 직접 찾아 답변 초안을 작성한다.",
                "고객문의 응답 지원 Agent",
                10.0,
                4,
                5,
                4,
                3,
                4,
                4,
                4,
                3,
                3,
            )
        )

    return specs


def build_official_source_payloads(
    official_docs: list[OfficialUrlDocument],
    dart_company: DartCompany | None,
) -> list[dict[str, Any]]:
    """build_official_source_payloads 함수. 입력 state나 domain 객체를 조합해 downstream에서 사용할 구조화된 payload를 만든다."""
    sources: list[dict[str, Any]] = []

    if dart_company is not None:
        sources.append(
            {
                "label": "[DART-기업개황]",
                "source_type": "opendart_company_overview",
                "title": f"{dart_company.corp_name} OpenDART 기업개황",
                "url": None,
                "content": dart_company.to_document_content(),
            }
        )

    for index, doc in enumerate(official_docs, start=1):
        sources.append(
            {
                "label": f"[공식URL-{index}]",
                "source_type": "official_url",
                "title": doc.title,
                "url": doc.url,
                "content": doc.content,
            }
        )

    return sources


def build_discovery_metadata(spec: dict[str, Any]) -> dict[str, Any]:
    """build_discovery_metadata 함수. 입력 state나 domain 객체를 조합해 downstream에서 사용할 구조화된 payload를 만든다."""
    return {
        "discovery_mode": spec.get("discovery_mode"),
        "discovery_warning": spec.get("discovery_warning"),
        "evidence_labels": spec.get("evidence_labels", []),
        "suitability_rationale": spec.get("suitability_rationale"),
        "score_rationale": spec.get("score_rationale", {}),
        "source": "company_process_discovery_agent",
    }


def create_business_processes(
    db: Session,
    company_id: int,
    departments: dict[str, Department],
    process_specs: list[dict[str, Any]],
) -> list[BusinessProcess]:
    """create_business_processes 함수. DB record 또는 domain 객체를 생성하고 필요한 기본값/관계를 함께 설정한다."""
    ensure_discovery_metadata_column()
    rows: list[BusinessProcess] = []

    for spec in process_specs:
        department = departments.get(spec.get("department")) or departments["AX전략/기획"]
        discovery_note = ""
        if spec.get("discovery_mode"):
            discovery_note = f"\n\n생성방식: {spec.get('discovery_mode')}"
        if spec.get("discovery_warning"):
            discovery_note += f"\n주의: {spec.get('discovery_warning')}"

        row = BusinessProcess(
            company_id=company_id,
            department_id=department.id,
            name=spec["name"],
            target_user=spec["target_user"],
            problem=spec["problem"],
            current_workflow=f"{spec.get('current_workflow') or ''}{discovery_note}".strip(),
            weekly_hours=spec["weekly_hours"],
            hourly_cost=40000,
            expected_effect=spec["expected_effect"],
            repeatability=spec["repeatability"],
            document_dependency=spec["document_dependency"],
            decision_complexity=spec["decision_complexity"],
            data_accessibility=spec["data_accessibility"],
            tech_feasibility=spec["tech_feasibility"],
            user_acceptance=spec["user_acceptance"],
            risk_score=spec["risk_score"],
            implementation_cost_score=spec["implementation_cost_score"],
            security_level="internal",
            candidate_agent_name=spec["candidate_agent_name"],
            discovery_metadata=build_discovery_metadata(spec),
        )
        db.add(row)
        rows.append(row)

    db.commit()
    for row in rows:
        db.refresh(row)
    return rows


def create_source_documents(
    db: Session,
    company_id: int,
    official_docs: list[OfficialUrlDocument],
    dart_company: DartCompany | None,
) -> list[ProcessDocument]:
    """create_source_documents 함수. DB record 또는 domain 객체를 생성하고 필요한 기본값/관계를 함께 설정한다."""
    rows: list[ProcessDocument] = []

    if dart_company is not None:
        row = ProcessDocument(
            company_id=company_id,
            process_id=None,
            title=f"{dart_company.corp_name} OpenDART 기업개황",
            document_type="opendart_company_overview",
            content=dart_company.to_document_content(),
            department="공식공시",
            security_level="public_official",
            contains_sensitive_info=False,
        )
        db.add(row)
        rows.append(row)

    for doc in official_docs:
        content = f"공식 URL: {doc.url}\n문서 제목: {doc.title}\n\n{doc.content}"
        row = ProcessDocument(
            company_id=company_id,
            process_id=None,
            title=doc.title[:200],
            document_type="official_url",
            content=content,
            department="공식웹사이트",
            security_level="public_official",
            contains_sensitive_info=False,
        )
        db.add(row)
        rows.append(row)

    db.commit()
    for row in rows:
        db.refresh(row)
    return rows


def create_analysis_project(db: Session, company_id: int, company_name: str) -> AnalysisProject:
    """create_analysis_project 함수. DB record 또는 domain 객체를 생성하고 필요한 기본값/관계를 함께 설정한다."""
    project = AnalysisProject(
        company_id=company_id,
        title=f"{company_name} 공식자료 기반 AX 전환 진단",
        status="created",
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def bootstrap_company(
    db: Session,
    company_name: str,
    official_urls: list[str] | None = None,
    dart_api_key: str | None = None,
    corp_code: str | None = None,
    stock_code: str | None = None,
    create_project: bool = True,
    index: bool = True,
    reset_company_chunks: bool = False,
) -> BootstrapResult:
    """bootstrap_company 함수. 회사 bootstrap을 서비스 함수 형태로 제공한다. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    warnings: list[str] = []
    official_urls = official_urls or []

    dart_company = None
    if dart_api_key:
        try:
            dart_company = load_dart_company(
                api_key=dart_api_key,
                company_name=company_name,
                corp_code=corp_code,
                stock_code=stock_code,
            )
            if dart_company is None:
                warnings.append("OpenDART에서 회사 고유번호를 찾지 못했습니다.")
        except Exception as exc:
            warnings.append(f"OpenDART 수집 실패: {type(exc).__name__}: {exc}")

    official_docs: list[OfficialUrlDocument] = []
    for url in official_urls:
        try:
            official_docs.append(load_official_url(url))
        except Exception as exc:
            warnings.append(f"공식 URL 수집 실패: {url} ({type(exc).__name__}: {exc})")

    if dart_company is None and not official_docs:
        raise ValueError("No official source was collected. Provide --official-url or --dart-api-key.")

    combined_parts = []
    if dart_company is not None:
        combined_parts.append(dart_company.to_document_content())
    combined_parts.extend(doc.content for doc in official_docs)
    combined_text = "\n\n".join(combined_parts)

    company = create_company(
        db=db,
        company_name=dart_company.corp_name if dart_company is not None else company_name,
        combined_text=combined_text,
        dart_company=dart_company,
    )
    departments = create_default_departments(db, company_id=company.id)
    create_default_systems(db, company_id=company.id)

    fallback_process_specs = build_process_specs(combined_text)
    official_sources = build_official_source_payloads(
        official_docs=official_docs,
        dart_company=dart_company,
    )
    discovered_process_specs = discover_company_process_specs(
        company_name=company.name,
        official_sources=official_sources,
        fallback_processes=fallback_process_specs,
    )

    discovery_mode = discovered_process_specs[0].get("discovery_mode") if discovered_process_specs else None
    discovery_warning = discovered_process_specs[0].get("discovery_warning") if discovered_process_specs else None
    if discovery_warning:
        warnings.append(discovery_warning)

    processes = create_business_processes(
        db=db,
        company_id=company.id,
        departments=departments,
        process_specs=discovered_process_specs,
    )
    documents = create_source_documents(
        db=db,
        company_id=company.id,
        official_docs=official_docs,
        dart_company=dart_company,
    )
    project = create_analysis_project(db, company_id=company.id, company_name=company.name) if create_project else None

    chunk_count = 0
    if index:
        if reset_company_chunks:
            delete_existing_chunks(db, company_id=company.id)
        for document in documents:
            chunk_count += index_single_document(db=db, document=document)

    return BootstrapResult(
        company_id=company.id,
        project_id=project.id if project else None,
        document_ids=[document.id for document in documents],
        process_ids=[process.id for process in processes],
        chunk_count=chunk_count,
        source_count=len(documents),
        warnings=warnings,
        discovery_mode=discovery_mode,
    )
