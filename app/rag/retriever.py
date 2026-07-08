# app/rag/retriever.py

from __future__ import annotations

import argparse
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.llm import embed_query_with_retry
from app.db.database import SessionLocal
from app.db.models import DocumentChunk, ProcessDocument
from app.security.access_control import DEFAULT_ROLE, allowed_security_levels


def embed_query(query: str) -> list[float]:
    return embed_query_with_retry(query)


def search_similar_chunks(
    db: Session,
    query: str,
    company_id: int,
    top_k: int = 5,
    process_id: int | None = None,
    max_distance: float | None = None,
    user_role: str | None = DEFAULT_ROLE,
) -> list[dict[str, Any]]:
    query_embedding = embed_query(query)
    allowed_levels = allowed_security_levels(user_role)

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
            ProcessDocument.allowed_roles,
            distance,
        )
        .join(ProcessDocument, ProcessDocument.id == DocumentChunk.document_id)
        .where(DocumentChunk.company_id == company_id)
        .where(ProcessDocument.security_level.in_(allowed_levels))
    )

    if process_id is not None:
        stmt = stmt.where(DocumentChunk.process_id == process_id)

    if max_distance is not None:
        stmt = stmt.where(distance <= max_distance)

    stmt = stmt.order_by(distance).limit(top_k * 3)

    rows = db.execute(stmt).all()

    results: list[dict[str, Any]] = []

    for row in rows:
        allowed_roles = row.allowed_roles or []
        if allowed_roles and user_role not in allowed_roles and user_role != "admin":
            continue

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
        if len(results) >= top_k:
            break

    return results


def merge_chunk_results(
    *result_groups: list[dict[str, Any]],
    top_k: int,
) -> list[dict[str, Any]]:
    merged: dict[int, dict[str, Any]] = {}

    for group in result_groups:
        for item in group:
            chunk_id = int(item.get("chunk_id") or 0)

            if not chunk_id:
                continue

            existing = merged.get(chunk_id)

            if existing is None or float(item.get("distance") or 999) < float(existing.get("distance") or 999):
                merged[chunk_id] = item

    return sorted(
        merged.values(),
        key=lambda item: float(item.get("distance") or 999),
    )[:top_k]


def retrieve_contexts_for_processes(
    db: Session,
    processes: list[dict[str, Any]],
    company_id: int,
    top_k: int = 3,
    include_company_wide: bool = True,
    user_role: str | None = DEFAULT_ROLE,
) -> dict[str, list[dict[str, Any]]]:
    """
    LangGraph node에서 쓰기 좋은 형태로 업무별 RAG context를 반환한다.
    key는 process_id 문자열로 둔다.

    업무 연결 문서와 회사 전체 문서를 함께 검색하되, user_role이 접근할 수 있는
    security_level/allowed_roles 문서만 반환한다.
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

        process_specific_results = search_similar_chunks(
            db=db,
            query=query,
            company_id=company_id,
            process_id=process_id,
            top_k=top_k,
            user_role=user_role,
        )

        if include_company_wide:
            company_wide_results = search_similar_chunks(
                db=db,
                query=query,
                company_id=company_id,
                process_id=None,
                top_k=top_k,
                user_role=user_role,
            )
            contexts[str(process_id)] = merge_chunk_results(
                process_specific_results,
                company_wide_results,
                top_k=top_k,
            )
        else:
            contexts[str(process_id)] = process_specific_results

    return contexts


def demo_search(
    query: str,
    company_id: int,
    process_id: int | None,
    top_k: int,
    user_role: str,
) -> None:
    with SessionLocal() as db:
        results = search_similar_chunks(
            db=db,
            query=query,
            company_id=company_id,
            process_id=process_id,
            top_k=top_k,
            user_role=user_role,
        )

    print(f"query: {query}")
    print(f"results: {len(results)}")

    for idx, item in enumerate(results, start=1):
        print("\n" + "=" * 80)
        print(f"[{idx}] {item['title']}")
        print(f"distance={item['distance']} similarity={item['similarity']}")
        print(f"document_type={item['document_type']} security={item['security_level']}")
        print(f"process_id={item.get('process_id')} document_id={item.get('document_id')} chunk_id={item.get('chunk_id')}")
        print(item["content"][:500])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("query", type=str)
    parser.add_argument("--company-id", type=int, default=1)
    parser.add_argument("--process-id", type=int, default=None)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--user-role", type=str, default=DEFAULT_ROLE)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    demo_search(
        query=args.query,
        company_id=args.company_id,
        process_id=args.process_id,
        top_k=args.top_k,
        user_role=args.user_role,
    )
