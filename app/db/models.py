# app/db/models.py

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class Company(Base):
    __tablename__ = "companies"

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
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str | None] = mapped_column(Text, nullable=True)
    main_pain_points: Mapped[str | None] = mapped_column(Text, nullable=True)

    company: Mapped["Company"] = relationship(back_populates="departments")
    processes: Mapped[list["BusinessProcess"]] = relationship(back_populates="department")


class EnterpriseSystem(Base):
    __tablename__ = "systems"

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
    __tablename__ = "business_processes"

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

    company: Mapped["Company"] = relationship(back_populates="processes")
    department: Mapped["Department"] = relationship(back_populates="processes")
    documents: Mapped[list["ProcessDocument"]] = relationship(back_populates="process")
    chunks: Mapped[list["DocumentChunk"]] = relationship(back_populates="process")


class ProcessDocument(Base):
    __tablename__ = "process_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    process_id: Mapped[int | None] = mapped_column(
        ForeignKey("business_processes.id"),
        nullable=True,
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    document_type: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    security_level: Mapped[str] = mapped_column(String(50), default="internal")
    contains_sensitive_info: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    company: Mapped["Company"] = relationship(back_populates="documents")
    process: Mapped["BusinessProcess"] = relationship(back_populates="documents")
    chunks: Mapped[list["DocumentChunk"]] = relationship(back_populates="document")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("process_documents.id"), nullable=False)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    process_id: Mapped[int | None] = mapped_column(
        ForeignKey("business_processes.id"),
        nullable=True,
    )

    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # SQLAlchemy 내부 metadata 이름과 충돌을 피하려고 chunk_metadata로 사용한다.
    chunk_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # text-embedding-3-small 기본 차원은 1536
    embedding: Mapped[list[float]] = mapped_column(VECTOR(1536), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    document: Mapped["ProcessDocument"] = relationship(back_populates="chunks")
    process: Mapped["BusinessProcess"] = relationship(back_populates="chunks")


class AnalysisProject(Base):
    __tablename__ = "analysis_projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="created")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("analysis_projects.id"), nullable=False)

    node_name: Mapped[str] = mapped_column(String(100), nullable=False)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class HumanReview(Base):
    __tablename__ = "human_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("analysis_projects.id"), nullable=False)

    reviewer_name: Mapped[str] = mapped_column(String(100), nullable=False)
    decision: Mapped[str] = mapped_column(String(50), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("analysis_projects.id"), nullable=True)

    node_name: Mapped[str] = mapped_column(String(100), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)