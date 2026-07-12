# app/ingestion/service.py

"""문서 ingestion service layer.

API/CLI가 공통으로 사용할 수 있도록 파일 저장, ProcessDocument 생성, chunk 색인 호출을
하나의 함수로 묶는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.llm import embed_documents_with_retry
from app.db.models import BusinessProcess, Company, DocumentChunk, ProcessDocument
from app.ingestion.loaders import load_document_text
from app.rag.chunker import chunk_text
from app.rag.indexer import batched
from app.storage.file_store import StoredFile, save_original_file

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
    """문서 ingestion 결과와 생성된 document/chunk 수를 담는 값 객체다."""
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
    file_storage_uri: str | None
    original_filename: str | None
    file_size_bytes: int | None
    file_checksum_sha256: str | None
    uploaded_by_user_id: str | None

    def to_dict(self) -> dict[str, Any]:
        """dataclass/value object를 JSON 직렬화 가능한 dict로 변환한다."""
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
            "file_storage_uri": self.file_storage_uri,
            "original_filename": self.original_filename,
            "file_size_bytes": self.file_size_bytes,
            "file_checksum_sha256": self.file_checksum_sha256,
            "uploaded_by_user_id": self.uploaded_by_user_id,
        }


def detect_sensitive_info(text: str) -> bool:
    """detect_sensitive_info 함수. 텍스트/state에서 특정 신호나 risk flag를 탐지한다."""
    lowered = text.lower()
    return any(re.search(pattern, lowered, re.IGNORECASE) for pattern in SENSITIVE_PATTERNS)


def validate_company_and_process(db: Session, company_id: int, process_id: int | None = None) -> None:
    """업로드 문서가 존재하는 회사와 그 회사 소속 업무에만 연결되도록 검증한다."""
    company = db.get(Company, company_id)
    if company is None:
        raise ValueError(f"Company not found: {company_id}")

    if process_id is None:
        return

    process = db.get(BusinessProcess, process_id)
    if process is None:
        raise ValueError(f"BusinessProcess not found: {process_id}")
    if int(process.company_id) != int(company_id):
        raise ValueError(f"process_id={process_id} belongs to company_id={process.company_id}, but company_id={company_id} was provided.")


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
    stored_file: StoredFile | None = None,
    uploaded_by_user_id: str | None = None,
) -> ProcessDocument:
    """업로드/수집 문서 내용을 ProcessDocument row로 저장하고 민감정보 flag를 보정한다."""
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
        file_storage_uri=stored_file.storage_uri if stored_file else None,
        original_filename=stored_file.original_filename if stored_file else None,
        file_size_bytes=stored_file.size_bytes if stored_file else None,
        file_checksum_sha256=stored_file.checksum_sha256 if stored_file else None,
        uploaded_by_user_id=uploaded_by_user_id,
    )

    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def delete_document_chunks(db: Session, document_id: int) -> None:
    """delete_document_chunks 함수. 재색인/정리 과정에서 기존 데이터를 안전하게 삭제한다."""
    db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
    db.commit()


def index_single_document(
    db: Session,
    document: ProcessDocument,
    chunk_size: int = 800,
    chunk_overlap: int = 120,
    batch_size: int = 64,
    reset_existing: bool = True,
    chunk_strategy: str | None = None,
    semantic_similarity_threshold: float | None = None,
    semantic_min_chunk_chars: int | None = None,
) -> int:
    """단일 ProcessDocument를 chunking/embedding하여 DocumentChunk로 저장한다."""
    if reset_existing:
        delete_document_chunks(db, document_id=document.id)

    settings = get_settings()
    resolved_chunk_strategy = chunk_strategy or settings.rag_chunk_strategy
    resolved_similarity_threshold = (
        semantic_similarity_threshold
        if semantic_similarity_threshold is not None
        else settings.rag_semantic_similarity_threshold
    )
    resolved_min_chunk_chars = (
        semantic_min_chunk_chars
        if semantic_min_chunk_chars is not None
        else settings.rag_semantic_min_chunk_chars
    )

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
            "file_storage_uri": getattr(document, "file_storage_uri", None),
            "original_filename": getattr(document, "original_filename", None),
            "uploaded_by_user_id": getattr(document, "uploaded_by_user_id", None),
            "embedding_model": settings.embedding_model,
        },
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        strategy=resolved_chunk_strategy,
        semantic_similarity_threshold=resolved_similarity_threshold,
        semantic_min_chunk_chars=resolved_min_chunk_chars,
    )

    if not chunks:
        return 0

    texts = [chunk.content for chunk in chunks]
    vectors: list[list[float]] = []
    for text_batch in batched(texts, batch_size=batch_size):
        vectors.extend(embed_documents_with_retry(text_batch))

    rows = [
        DocumentChunk(
            document_id=document.id,
            company_id=document.company_id,
            process_id=document.process_id,
            chunk_index=chunk.chunk_index,
            content=chunk.content,
            chunk_metadata=chunk.metadata,
            embedding=vector,
        )
        for chunk, vector in zip(chunks, vectors, strict=True)
    ]

    db.add_all(rows)
    db.commit()
    return len(rows)


def infer_document_type(path: Path, provided: str | None = None) -> str:
    """infer_document_type 함수. 명시 입력이 없을 때 텍스트나 metadata에서 보수적인 추정값을 만든다."""
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
    uploaded_by_user_id: str | None = None,
    store_original: bool = True,
    index: bool = True,
    chunk_size: int = 800,
    chunk_overlap: int = 120,
    chunk_strategy: str | None = None,
    semantic_similarity_threshold: float | None = None,
    semantic_min_chunk_chars: int | None = None,
    batch_size: int = 64,
) -> IngestResult:
    """업로드/로컬 파일을 ProcessDocument로 저장하고 필요하면 RAG 색인까지 수행한다."""
    path = Path(file_path)
    content = load_document_text(path)
    if not content.strip():
        raise ValueError(f"No extractable text in file: {path}")

    stored_file = save_original_file(path, company_id=company_id, original_filename=path.name) if store_original else None
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
        stored_file=stored_file,
        uploaded_by_user_id=uploaded_by_user_id,
    )

    chunk_count = 0
    if index:
        chunk_count = index_single_document(
            db=db,
            document=document,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            batch_size=batch_size,
            chunk_strategy=chunk_strategy,
            semantic_similarity_threshold=semantic_similarity_threshold,
            semantic_min_chunk_chars=semantic_min_chunk_chars,
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
        file_storage_uri=document.file_storage_uri,
        original_filename=document.original_filename,
        file_size_bytes=document.file_size_bytes,
        file_checksum_sha256=document.file_checksum_sha256,
        uploaded_by_user_id=document.uploaded_by_user_id,
    )
