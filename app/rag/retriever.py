# app/rag/retriever.py

from __future__ import annotations

import argparse
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.llm import get_embedding_model
from app.db.database import SessionLocal
from app.db.models import DocumentChunk, ProcessDocument


def embed_query(query: str) -> list[float]:
    embeddings = get_embedding_model()
    return embeddings.embed_query(query)


def search_similar_chunks(
    db: Session,
    query: str,
    company_id: int,
    top_k: int = 5,
    process_id: int | None = None,
    max_distance: float | None = None,
) -> list[dict[str, Any]]:
    query_embedding = embed_query(query)

    distance = DocumentChunk.embedding.cosine_distance(query_embedding).label("distance")

    stmt = (
        select(
            DocumentChunk.id,
            DocumentChunk.document_id,
            DocumentChunk.company_id,
            DocumentChunk.process_id,
            DocumentChunk.chunk_index,
            DocumentChunk.content,
            DocumentChunk.chunk_metadata,
            ProcessDocument.title,
            ProcessDocument.document_type,
            ProcessDocument.security_level,
            ProcessDocument.contains_sensitive_info,
            distance,
        )
        .join(ProcessDocument, ProcessDocument.id == DocumentChunk.document_id)
        .where(DocumentChunk.company_id == company_id)
    )

    if process_id is not None:
        stmt = stmt.where(DocumentChunk.process_id == process_id)

    if max_distance is not None:
        stmt = stmt.where(distance <= max_distance)

    stmt = stmt.order_by(distance).limit(top_k)

    rows = db.execute(stmt).all()

    results: list[dict[str, Any]] = []

    for row in rows:
        distance_value = float(row.distance)
        similarity = 1.0 - distance_value

        results.append(
            {
                "chunk_id": row.id,
                "document_id": row.document_id,
                "company_id": row.company_id,
                "process_id": row.process_id,
                "chunk_index": row.chunk_index,
                "title": row.title,
                "document_type": row.document_type,
                "security_level": row.security_level,
                "contains_sensitive_info": row.contains_sensitive_info,
                "content": row.content,
                "metadata": row.chunk_metadata,
                "distance": round(distance_value, 6),
                "similarity": round(similarity, 6),
            }
        )

    return results


def retrieve_contexts_for_processes(
    db: Session,
    processes: list[dict[str, Any]],
    company_id: int,
    top_k: int = 3,
) -> dict[str, list[dict[str, Any]]]:
    """
    LangGraph node에서 쓰기 좋은 형태로 업무별 RAG context를 반환한다.
    key는 process_id 문자열로 둔다. JSON 직렬화와 State 저장이 편해진다.
    """
    contexts: dict[str, list[dict[str, Any]]] = {}

    for process in processes:
        process_id = int(process["id"])
        query = (
            f"업무명: {process.get('name', '')}\n"
            f"문제: {process.get('problem', '')}\n"
            f"현재 업무 흐름: {process.get('current_workflow', '')}\n"
            f"후보 Agent: {process.get('candidate_agent_name', '')}"
        )

        contexts[str(process_id)] = search_similar_chunks(
            db=db,
            query=query,
            company_id=company_id,
            process_id=process_id,
            top_k=top_k,
        )

    return contexts


def demo_search(
    query: str,
    company_id: int,
    process_id: int | None,
    top_k: int,
) -> None:
    with SessionLocal() as db:
        results = search_similar_chunks(
            db=db,
            query=query,
            company_id=company_id,
            process_id=process_id,
            top_k=top_k,
        )

    print(f"query: {query}")
    print(f"results: {len(results)}")

    for idx, item in enumerate(results, start=1):
        print("\n" + "=" * 80)
        print(f"[{idx}] {item['title']}")
        print(f"distance={item['distance']} similarity={item['similarity']}")
        print(f"document_type={item['document_type']} security={item['security_level']}")
        print(item["content"][:500])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("query", type=str)
    parser.add_argument("--company-id", type=int, default=1)
    parser.add_argument("--process-id", type=int, default=None)
    parser.add_argument("--top-k", type=int, default=5)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    demo_search(
        query=args.query,
        company_id=args.company_id,
        process_id=args.process_id,
        top_k=args.top_k,
    )