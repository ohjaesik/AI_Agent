# app/ingestion/service.py

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.llm import embed_documents_with_retry
from app.db.models import BusinessProcess, Company, DocumentChunk, ProcessDocument
from app.ingestion.loaders import load_document_text
from app.rag.chunker import chunk_text
from app.rag.indexer import batched

SENSITIVE_PATTERNS = [
    r"주민등록번호",
    r"개인정보",
    r"비밀번호",
    r"password",
    r"passwd",
    r"secret",
    r"token",
    r"api[_-]?key",
    r"credential",
]


@dataclass(frozen=True)
class IngestResult:
    document_id: int
    company_id: int
    process_id: int | None
    title: str
    document_type: str
    text_length: int
    chunk_count: int
    indexed: bool
    security_level: str
    allowed_roles: list[str] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "company_id": self.company_id,
            "process_id": self.process_id,
            "title": self.title,
            "document_type": self.document_type,
            "text_length": self.text_length,
            "chunk_count": self.chunk_count,
            "indexed": self.indexed,
            "security_level": self.security_level,
            "allowed_roles": self.allowed_roles,
        }


def detect_sensitive_info(text: str) -> bool:
    lowered = text.lower()
    return any(re.search(pattern, lowered, re.IGNORECASE) for pattern in SENSITIVE_PATTERNS)


def validate_company_and_process(
    db: Session,
    company_id: int,
    process_id: int | None = None,
) -> None:
    company = db.get(Company, company_id)

    if company is None:
        raise ValueError(f"Company not found: {company_id}")

    if process_id is None:
        return

    process = db.get(BusinessProcess, process_id)

    if process is None:
        raise ValueError(f"BusinessProcess not found: {process_id}")

    if int(process.company_id) != int(company_id):
        raise ValueError(
            f"process_id={process_id} belongs to company_id={process.company_id}, "
            f"but company_id={company_id} was provided."
        )


def create_process_document(
    db: Session,
    company_id: int,
    content: str,
    title: str,
    document_type: str,
    process_id: int | None = None,
    department: str | None = None,
    security_level: str = "internal",
    contains_sensitive_info: bool | None = None,
    source_url: str | None = None,
    allowed_roles: list[str] | None = None,
) -> ProcessDocument:
    validate_company_and_process(db, company_id=company_id, process_id=process_id)

    if contains_sensitive_info is None:
        contains_sensitive_info = detect_sensitive_info(content)

    document = ProcessDocument(
        company_id=company_id,
        process_id=process_id,
        title=title,
        document_type=document_type,
        content=content,
        department=department,
        security_level=security_level,
        contains_sensitive_info=contains_sensitive_info,
        source_url=source_url,
        allowed_roles=allowed_roles,
    )

    db.add(document)
    db.commit()
    db.refresh(document)

    return document


def delete_document_chunks(db: Session, document_id: int) -> None:
    db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
    db.commit()


def index_single_document(
    db: Session,
    document: ProcessDocument,
    chunk_size: int = 800,
    chunk_overlap: int = 120,
    batch_size: int = 64,
    reset_existing: bool = True,
) -> int:
    if reset_existing:
        delete_document_chunks(db, document_id=document.id)

    chunks = chunk_text(
        text=document.content,
        base_metadata={
            "document_id": document.id,
            "company_id": document.company_id,
            "process_id": document.process_id,
            "title": document.title,
            "document_type": document.document_type,
            "department": document.department,
            "security_level": document.security_level,
            "contains_sensitive_info": document.contains_sensitive_info,
            "source_url": getattr(document, "source_url", None),
            "allowed_roles": getattr(document, "allowed_roles", None),
        },
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    if not chunks:
        return 0

    texts = [chunk.content for chunk in chunks]
    vectors: list[list[float]] = []

    for text_batch in batched(texts, batch_size=batch_size):
        vectors.extend(embed_documents_with_retry(text_batch))

    rows = []

    for chunk, vector in zip(chunks, vectors, strict=True):
        rows.append(
            DocumentChunk(
                document_id=document.id,
                company_id=document.company_id,
                process_id=document.process_id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                chunk_metadata=chunk.metadata,
                embedding=vector,
            )
        )

    db.add_all(rows)
    db.commit()

    return len(rows)


def infer_document_type(path: Path, provided: str | None = None) -> str:
    if provided:
        return provided

    suffix = path.suffix.lower().lstrip(".")
    return suffix or "text"


def ingest_file(
    db: Session,
    file_path: str | Path,
    company_id: int,
    process_id: int | None = None,
    title: str | None = None,
    document_type: str | None = None,
    department: str | None = None,
    security_level: str = "internal",
    contains_sensitive_info: bool | None = None,
    source_url: str | None = None,
    allowed_roles: list[str] | None = None,
    index: bool = True,
    chunk_size: int = 800,
    chunk_overlap: int = 120,
    batch_size: int = 64,
) -> IngestResult:
    path = Path(file_path)
    content = load_document_text(path)

    if not content.strip():
        raise ValueError(f"No extractable text in file: {path}")

    document = create_process_document(
        db=db,
        company_id=company_id,
        process_id=process_id,
        title=title or path.stem,
        document_type=infer_document_type(path, document_type),
        content=content,
        department=department,
        security_level=security_level,
        contains_sensitive_info=contains_sensitive_info,
        source_url=source_url,
        allowed_roles=allowed_roles,
    )

    chunk_count = 0

    if index:
        chunk_count = index_single_document(
            db=db,
            document=document,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            batch_size=batch_size,
        )

    return IngestResult(
        document_id=document.id,
        company_id=document.company_id,
        process_id=document.process_id,
        title=document.title,
        document_type=document.document_type,
        text_length=len(content),
        chunk_count=chunk_count,
        indexed=index,
        security_level=document.security_level,
        allowed_roles=document.allowed_roles,
    )
