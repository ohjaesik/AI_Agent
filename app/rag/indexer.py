# app/rag/indexer.py

"""문서 chunk를 embedding으로 색인하는 CLI/service 모듈.

ProcessDocument 본문을 chunking하고 OpenAI embedding을 만든 뒤 DocumentChunk table에
저장한다.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.llm import embed_documents_with_retry
from app.db.database import SessionLocal
from app.db.models import DocumentChunk, ProcessDocument
from app.rag.chunker import chunk_text


def batched(items: list[str], batch_size: int) -> Iterable[list[str]]:
    """batched 함수. 문서 chunk를 embedding으로 색인하는 CLI/service 모듈. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    for start in range(0, len(items), batch_size):
        yield items[start : start + batch_size]


def load_documents(
    db: Session,
    company_id: int | None = None,
) -> list[ProcessDocument]:
    """load_documents 함수. 외부/DB/파일 입력을 읽어 workflow에서 사용할 구조로 적재한다."""
    stmt = select(ProcessDocument).order_by(ProcessDocument.id)

    if company_id is not None:
        stmt = stmt.where(ProcessDocument.company_id == company_id)

    return list(db.execute(stmt).scalars().all())


def delete_existing_chunks(
    db: Session,
    company_id: int | None = None,
) -> None:
    """delete_existing_chunks 함수. 재색인/정리 과정에서 기존 데이터를 안전하게 삭제한다."""
    stmt = delete(DocumentChunk)

    if company_id is not None:
        stmt = stmt.where(DocumentChunk.company_id == company_id)

    db.execute(stmt)
    db.commit()


def build_chunk_payloads(
    documents: list[ProcessDocument],
    chunk_size: int,
    chunk_overlap: int,
    chunk_strategy: str,
    semantic_similarity_threshold: float,
    semantic_min_chunk_chars: int,
) -> list[dict]:
    """build_chunk_payloads 함수. 입력 state나 domain 객체를 조합해 downstream에서 사용할 구조화된 payload를 만든다."""
    payloads: list[dict] = []
    settings = get_settings()

    for document in documents:
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
                "embedding_model": settings.embedding_model,
            },
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            strategy=chunk_strategy,
            semantic_similarity_threshold=semantic_similarity_threshold,
            semantic_min_chunk_chars=semantic_min_chunk_chars,
        )

        for chunk in chunks:
            payloads.append(
                {
                    "document_id": document.id,
                    "company_id": document.company_id,
                    "process_id": document.process_id,
                    "chunk_index": chunk.chunk_index,
                    "content": chunk.content,
                    "chunk_metadata": chunk.metadata,
                }
            )

    return payloads


def embed_payloads(
    payloads: list[dict],
    batch_size: int = 64,
) -> list[dict]:
    """embed_payloads 함수. 문서 chunk를 embedding으로 색인하는 CLI/service 모듈. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    if not payloads:
        return []

    settings = get_settings()
    texts = [item["content"] for item in payloads]
    vectors: list[list[float]] = []

    for text_batch in batched(texts, batch_size):
        vectors.extend(embed_documents_with_retry(text_batch))

    if len(vectors) != len(payloads):
        raise RuntimeError(
            f"Embedding count mismatch: payloads={len(payloads)}, vectors={len(vectors)}"
        )

    for payload, vector in zip(payloads, vectors, strict=True):
        if len(vector) != settings.embedding_dim:
            raise ValueError(
                f"Embedding dimension mismatch. "
                f"expected={settings.embedding_dim}, actual={len(vector)}"
            )

        payload["embedding"] = vector

    return payloads


def save_chunks(
    db: Session,
    embedded_payloads: list[dict],
) -> int:
    """save_chunks 함수. 분석 결과나 사용자 결정을 DB 또는 파일에 저장한다."""
    rows = [
        DocumentChunk(
            document_id=item["document_id"],
            company_id=item["company_id"],
            process_id=item["process_id"],
            chunk_index=item["chunk_index"],
            content=item["content"],
            chunk_metadata=item["chunk_metadata"],
            embedding=item["embedding"],
        )
        for item in embedded_payloads
    ]

    db.add_all(rows)
    db.commit()

    return len(rows)


def index_documents(
    company_id: int | None = None,
    reset: bool = False,
    chunk_size: int = 800,
    chunk_overlap: int = 120,
    batch_size: int = 64,
    chunk_strategy: str | None = None,
    semantic_similarity_threshold: float | None = None,
    semantic_min_chunk_chars: int | None = None,
) -> int:
    """index_documents 함수. 문서 chunk를 embedding으로 색인하는 CLI/service 모듈. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    with SessionLocal() as db:
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

        if reset:
            delete_existing_chunks(db, company_id=company_id)

        documents = load_documents(db, company_id=company_id)

        if not documents:
            print("No process_documents found.")
            return 0

        payloads = build_chunk_payloads(
            documents=documents,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            chunk_strategy=resolved_chunk_strategy,
            semantic_similarity_threshold=resolved_similarity_threshold,
            semantic_min_chunk_chars=resolved_min_chunk_chars,
        )

        if not payloads:
            print("No chunks created.")
            return 0

        embedded_payloads = embed_payloads(
            payloads=payloads,
            batch_size=batch_size,
        )

        inserted_count = save_chunks(
            db=db,
            embedded_payloads=embedded_payloads,
        )

        print(f"Indexed documents: {len(documents)}")
        print(f"Inserted chunks: {inserted_count}")

        return inserted_count


def parse_args() -> argparse.Namespace:
    """CLI 실행 인자를 정의하고 argparse Namespace로 변환한다."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--company-id", type=int, default=None)
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--chunk-size", type=int, default=800)
    parser.add_argument("--chunk-overlap", type=int, default=120)
    parser.add_argument("--chunk-strategy", type=str, default=None, choices=["semantic", "similarity", "semantic_similarity", "recursive"])
    parser.add_argument("--semantic-similarity-threshold", type=float, default=None)
    parser.add_argument("--semantic-min-chunk-chars", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=64)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    index_documents(
        company_id=args.company_id,
        reset=args.reset,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        batch_size=args.batch_size,
        chunk_strategy=args.chunk_strategy,
        semantic_similarity_threshold=args.semantic_similarity_threshold,
        semantic_min_chunk_chars=args.semantic_min_chunk_chars,
    )
