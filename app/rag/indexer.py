# app/rag/indexer.py

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
    for start in range(0, len(items), batch_size):
        yield items[start : start + batch_size]


def load_documents(
    db: Session,
    company_id: int | None = None,
) -> list[ProcessDocument]:
    stmt = select(ProcessDocument).order_by(ProcessDocument.id)

    if company_id is not None:
        stmt = stmt.where(ProcessDocument.company_id == company_id)

    return list(db.execute(stmt).scalars().all())


def delete_existing_chunks(
    db: Session,
    company_id: int | None = None,
) -> None:
    stmt = delete(DocumentChunk)

    if company_id is not None:
        stmt = stmt.where(DocumentChunk.company_id == company_id)

    db.execute(stmt)
    db.commit()


def build_chunk_payloads(
    documents: list[ProcessDocument],
    chunk_size: int,
    chunk_overlap: int,
) -> list[dict]:
    payloads: list[dict] = []

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
            },
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
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
) -> int:
    with SessionLocal() as db:
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--company-id", type=int, default=None)
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--chunk-size", type=int, default=800)
    parser.add_argument("--chunk-overlap", type=int, default=120)
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
    )
