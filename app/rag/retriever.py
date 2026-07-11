# app/rag/retriever.py
"""pgvector 기반 RAG 검색 로직을 제공한다.

이 파일은 색인된 `DocumentChunk`를 embedding cosine distance로 검색하고,
업무별로 여러 검색 전략을 조합해 근거 누락을 줄인다.

검색 전략:
- `workflow_full_context`: 업무명/문제/현재 흐름/후보 Agent를 모두 넣은 긴 query
- `problem_and_user_intent`: 문제와 대상 사용자 관점의 query
- `automation_evidence_keywords`: 자동화 가능성, 문서 의존도, 데이터 입력 관점의 query

각 전략은 process-specific 검색과 company-wide 검색으로 나뉘며, 최종 결과는
chunk_id 기준으로 병합된다. 결과 chunk에는 `retrieval_strategy_hits`와
`retrieval_query_plan`을 남겨 어떤 검색 방식으로 근거가 잡혔는지 추적한다.
"""

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
    """검색 query를 embedding vector로 변환한다."""

    return embed_query_with_retry(query)


def search_similar_chunks(
    db: Session,
    query: str,
    company_id: int,
    top_k: int = 5,
    process_id: int | None = None,
    max_distance: float | None = None,
    user_role: str | None = DEFAULT_ROLE,
    query_strategy: str = "single_query",
) -> list[dict[str, Any]]:
    """단일 query로 유사 chunk를 검색한다.

    보안 처리:
    - 문서의 `security_level`이 현재 user_role이 접근 가능한 수준인지 먼저 필터링한다.
    - `allowed_roles`가 있으면 admin이 아닌 이상 해당 role만 결과를 볼 수 있다.

    검색 처리:
    - cosine distance가 낮을수록 유사하므로 distance 오름차순으로 정렬한다.
    - DB에서는 `top_k * 3`만큼 넉넉히 가져온 뒤 role 필터를 한 번 더 적용한다.
    """

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

        # retrieval_strategy_hits는 여러 query 전략 결과를 병합할 때 누적된다.
        # 단일 검색 단계에서는 현재 전략 하나만 넣어 둔다.
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
                "retrieval_strategy": query_strategy,
                "retrieval_query": query,
                "retrieval_strategy_hits": [
                    {
                        "strategy": query_strategy,
                        "distance": round(distance_value, 6),
                        "similarity": round(similarity, 6),
                    }
                ],
            }
        )
        if len(results) >= top_k:
            break

    return results


def build_process_retrieval_queries(process: dict[str, Any]) -> list[dict[str, str]]:
    """근거 누락을 줄이기 위해 업무별 RAG query를 세 가지 관점으로 만든다.

    하나의 query만 쓰면 문서 표현 방식과 업무 후보 표현 방식이 조금만 달라도
    근거를 놓칠 수 있다. 그래서 workflow 전체 문맥, 문제/사용자 의도, 자동화
    키워드 관점을 나눠 검색한다.
    """

    name = str(process.get("name") or "")
    problem = str(process.get("problem") or "")
    workflow = str(process.get("current_workflow") or "")
    candidate_agent = str(process.get("candidate_agent_name") or "")
    target_user = str(process.get("target_user") or "")
    query_items = [
        {
            "strategy": "workflow_full_context",
            "query": (
                f"업무명: {name}\n"
                f"문제: {problem}\n"
                f"현재 업무 흐름: {workflow}\n"
                f"후보 Agent: {candidate_agent}"
            ),
        },
        {
            "strategy": "problem_and_user_intent",
            "query": (
                f"{name} 업무의 병목, 반복 작업, 대상 사용자({target_user}) 불편, 문제 정의: {problem}"
            ),
        },
        {
            "strategy": "automation_evidence_keywords",
            "query": (
                f"{name} {candidate_agent} 자동화 가능성 문서 의존도 의사결정 복잡도 데이터 입력 "
                f"현재 프로세스 근거: {workflow}"
            ),
        },
    ]
    return [item for item in query_items if item["query"].strip()]


def merge_chunk_results(
    *result_groups: list[dict[str, Any]],
    top_k: int,
) -> list[dict[str, Any]]:
    """여러 검색 전략에서 나온 chunk 결과를 chunk_id 기준으로 병합한다.

    같은 chunk가 여러 전략에서 잡히면 가장 낮은 distance를 대표 점수로 쓰고,
    어떤 전략들에서 hit 되었는지는 `retrieval_strategy_hits`에 모두 남긴다.
    """

    merged: dict[int, dict[str, Any]] = {}

    for group in result_groups:
        for item in group:
            chunk_id = int(item.get("chunk_id") or 0)

            if not chunk_id:
                continue

            existing = merged.get(chunk_id)

            if existing is None or float(item.get("distance") or 999) < float(existing.get("distance") or 999):
                # 더 가까운 검색 결과가 나왔으면 대표 chunk payload를 교체하되,
                # 기존 strategy hit 기록은 잃지 않도록 이어 붙인다.
                if existing is not None:
                    item["retrieval_strategy_hits"] = list(existing.get("retrieval_strategy_hits", [])) + list(
                        item.get("retrieval_strategy_hits", [])
                    )
                merged[chunk_id] = item
            elif existing is not None:
                # 대표 결과는 유지하고, 추가 전략에서 hit 되었다는 사실만 누적한다.
                existing["retrieval_strategy_hits"] = list(existing.get("retrieval_strategy_hits", [])) + list(
                    item.get("retrieval_strategy_hits", [])
                )

    results = sorted(
        merged.values(),
        key=lambda item: float(item.get("distance") or 999),
    )[:top_k]
    for item in results:
        strategies = [
            str(hit.get("strategy"))
            for hit in item.get("retrieval_strategy_hits", []) or []
            if hit.get("strategy")
        ]
        item["retrieval_strategies"] = sorted(set(strategies))
    return results


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
        query_plan = build_process_retrieval_queries(process)[:3]
        process_specific_groups: list[list[dict[str, Any]]] = []
        company_wide_groups: list[list[dict[str, Any]]] = []

        for query_item in query_plan:
            query = query_item["query"]
            strategy = query_item["strategy"]
            # process_id가 걸린 chunk를 먼저 찾는다. 업무와 직접 연결된 문서가 있으면
            # 이 결과가 가장 신뢰도 높은 근거가 된다.
            process_specific_groups.append(
                search_similar_chunks(
                    db=db,
                    query=query,
                    company_id=company_id,
                    process_id=process_id,
                    top_k=top_k,
                    user_role=user_role,
                    query_strategy=f"{strategy}:process_specific",
                )
            )
            if include_company_wide:
                # 공식자료나 공통 규정처럼 process_id가 비어 있는 문서도 근거가 될 수 있다.
                # 그래서 company-wide 검색을 병행하고, 나중에 같은 chunk는 병합한다.
                company_wide_groups.append(
                    search_similar_chunks(
                        db=db,
                        query=query,
                        company_id=company_id,
                        process_id=None,
                        top_k=top_k,
                        user_role=user_role,
                        query_strategy=f"{strategy}:company_wide",
                    )
                )

        if include_company_wide:
            contexts[str(process_id)] = merge_chunk_results(
                *process_specific_groups,
                *company_wide_groups,
                top_k=top_k,
            )
        else:
            contexts[str(process_id)] = merge_chunk_results(*process_specific_groups, top_k=top_k)

        for chunk in contexts[str(process_id)]:
            # downstream evidence item과 workflow_state에서 "어떤 query 세트로 찾았는지"를
            # 볼 수 있게 모든 query plan을 chunk에 붙인다.
            chunk["retrieval_query_plan"] = query_plan

    return contexts


def demo_search(
    query: str,
    company_id: int,
    process_id: int | None,
    top_k: int,
    user_role: str,
) -> None:
    """CLI에서 RAG 검색만 빠르게 확인하는 개발용 helper."""

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
    """CLI 실행 인자를 정의하고 argparse Namespace로 변환한다."""
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
