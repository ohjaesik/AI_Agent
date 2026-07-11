# app/db/models.py

"""SQLAlchemy ORM model 정의.

회사, 프로젝트, 부서, 시스템, 업무 프로세스, 문서, chunk, 분석 결과, human review,
audit log table 구조를 선언한다.
"""

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class AppUser(Base):
    """로컬 API 인증에 사용하는 사용자 계정 table model이다."""
    __tablename__ = "app_users"
    __table_args__ = (UniqueConstraint("username", name="uq_app_users_username"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(50), default="analyst")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Company(Base):
    """분석 대상 회사의 기본 식별 정보와 설명을 저장하는 table model이다."""
    __tablename__ = "companies"
    __table_args__ = (UniqueConstraint("name", name="uq_companies_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    industry: Mapped[str] = mapped_column(String(100), nullable=False)
    size: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    departments: Mapped[list["Department"]] = relationship(back_populates="company")
    systems: Mapped[list["EnterpriseSystem"]] = relationship(back_populates="company")
    processes: Mapped[list["BusinessProcess"]] = relationship(back_populates="company")
    documents: Mapped[list["ProcessDocument"]] = relationship(back_populates="company")


class Department(Base):
    """회사 내부 부서/조직 단위를 저장하는 table model이다."""
    __tablename__ = "departments"
    __table_args__ = (UniqueConstraint("company_id", "name", name="uq_departments_company_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str | None] = mapped_column(Text, nullable=True)
    main_pain_points: Mapped[str | None] = mapped_column(Text, nullable=True)

    company: Mapped["Company"] = relationship(back_populates="departments")
    processes: Mapped[list["BusinessProcess"]] = relationship(back_populates="department")


class EnterpriseSystem(Base):
    """ERP/MES/CRM 같은 사내 시스템 정보를 저장하는 table model이다."""
    __tablename__ = "systems"
    __table_args__ = (UniqueConstraint("company_id", "name", name="uq_systems_company_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    system_type: Mapped[str] = mapped_column(String(50), nullable=False)
    owner_department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    data_access_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    api_available: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    company: Mapped["Company"] = relationship(back_populates="systems")


class BusinessProcess(Base):
    """AI Agent 도입 후보가 될 업무 프로세스와 discovery metadata를 저장하는 table model이다."""
    __tablename__ = "business_processes"
    __table_args__ = (UniqueConstraint("company_id", "name", "candidate_agent_name", name="uq_processes_company_name_agent"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"), nullable=False)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    target_user: Mapped[str] = mapped_column(String(100), nullable=False)
    problem: Mapped[str] = mapped_column(Text, nullable=False)
    current_workflow: Mapped[str | None] = mapped_column(Text, nullable=True)

    weekly_hours: Mapped[float] = mapped_column(Float, default=0.0)
    hourly_cost: Mapped[int] = mapped_column(Integer, default=40000)

    expected_effect: Mapped[int | None] = mapped_column(Integer, nullable=True)
    repeatability: Mapped[int | None] = mapped_column(Integer, nullable=True)
    document_dependency: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decision_complexity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data_accessibility: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tech_feasibility: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_acceptance: Mapped[int | None] = mapped_column(Integer, nullable=True)
    risk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    implementation_cost_score: Mapped[int | None] = mapped_column(Integer, nullable=True)

    security_level: Mapped[str] = mapped_column(String(50), default="internal")
    candidate_agent_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    discovery_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    company: Mapped["Company"] = relationship(back_populates="processes")
    department: Mapped["Department"] = relationship(back_populates="processes")
    documents: Mapped[list["ProcessDocument"]] = relationship(back_populates="process")
    chunks: Mapped[list["DocumentChunk"]] = relationship(back_populates="process")


class ProcessDocument(Base):
    """공식/내부 문서 원본과 보안 metadata를 저장하는 table model이다."""
    __tablename__ = "process_documents"
    __table_args__ = (UniqueConstraint("company_id", "document_type", "source_url", name="uq_documents_company_type_source_url"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    process_id: Mapped[int | None] = mapped_column(ForeignKey("business_processes.id"), nullable=True)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    document_type: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    security_level: Mapped[str] = mapped_column(String(50), default="internal")
    contains_sensitive_info: Mapped[bool] = mapped_column(Boolean, default=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    allowed_roles: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    file_storage_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    uploaded_by_user_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    company: Mapped["Company"] = relationship(back_populates="documents")
    process: Mapped["BusinessProcess"] = relationship(back_populates="documents")
    chunks: Mapped[list["DocumentChunk"]] = relationship(back_populates="document")


class DocumentChunk(Base):
    """RAG 검색용 chunk 본문, embedding, chunk metadata를 저장하는 table model이다."""
    __tablename__ = "document_chunks"
    __table_args__ = (UniqueConstraint("document_id", "chunk_index", name="uq_chunks_document_index"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("process_documents.id"), nullable=False)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    process_id: Mapped[int | None] = mapped_column(ForeignKey("business_processes.id"), nullable=True)

    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    embedding: Mapped[list[float]] = mapped_column(VECTOR(1536), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    document: Mapped["ProcessDocument"] = relationship(back_populates="chunks")
    process: Mapped["BusinessProcess"] = relationship(back_populates="chunks")


class AnalysisProject(Base):
    """회사별 AX 분석 실행 단위를 저장하는 table model이다."""
    __tablename__ = "analysis_projects"
    __table_args__ = (UniqueConstraint("company_id", "title", name="uq_analysis_projects_company_title"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="created")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AnalysisResult(Base):
    """각 graph node의 중간/최종 분석 결과 JSON을 저장하는 table model이다."""
    __tablename__ = "analysis_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("analysis_projects.id"), nullable=False)
    node_name: Mapped[str] = mapped_column(String(100), nullable=False)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class HumanReview(Base):
    """사람 검토자 또는 Supervisor auto approval 결정을 저장하는 table model이다."""
    __tablename__ = "human_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("analysis_projects.id"), nullable=False)
    reviewer_name: Mapped[str] = mapped_column(String(100), nullable=False)
    decision: Mapped[str] = mapped_column(String(50), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    """node/tool/API 실행 이력을 감사 추적용으로 저장하는 table model이다."""
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("analysis_projects.id"), nullable=True)
    node_name: Mapped[str] = mapped_column(String(100), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
