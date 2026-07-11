"""RAG 검색 결과와 내부 문서를 workflow evidence state로 변환한다.

`retrieve_context_node`는 DB/RAG 호출과 audit 저장을 담당하고, 이 모듈은 검색 결과를
downstream node가 공통으로 읽는 `evidence_items`, `used_sources`,
`retrieval_query_plan` 구조로 바꾸는 순수 로직을 담당한다.
"""

from __future__ import annotations

from typing import Any

from app.sources.collector import (
    build_used_sources,
    dedupe_evidence,
    internal_document_to_evidence,
    rag_chunk_to_evidence,
)


RAG_EVIDENCE_USED_FOR = [
    "process_analysis",
    "data_readiness",
    "risk_governance",
    "priority_ranking",
    "report_generation",
]

DOCUMENT_EVIDENCE_USED_FOR = [
    "industry_analysis",
    "business_process_analysis",
    "data_readiness",
    "risk_governance",
    "report_generation",
]


def build_retrieval_query_plan(contexts: dict[Any, list[dict[str, Any]]]) -> dict[Any, list[dict[str, Any]]]:
    """process별 검색 query plan trace를 첫 번째 chunk metadata에서 꺼낸다.

    retriever는 같은 process의 chunk마다 동일한 `retrieval_query_plan`을 붙인다.
    state에는 process별 요약만 필요하므로 첫 chunk의 plan만 남긴다.
    """

    return {
        process_id: (chunks[0].get("retrieval_query_plan") if chunks else [])
        for process_id, chunks in contexts.items()
    }


def build_retrieval_evidence_items(
    *,
    contexts: dict[Any, list[dict[str, Any]]],
    documents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """RAG chunk와 내부 문서를 표준 evidence item 목록으로 변환하고 중복을 제거한다."""

    evidence_items: list[dict[str, Any]] = []

    for chunks in contexts.values():
        for chunk in chunks or []:
            evidence_items.append(
                rag_chunk_to_evidence(
                    chunk,
                    used_for=RAG_EVIDENCE_USED_FOR,
                )
            )

    for document in documents:
        evidence_items.append(
            internal_document_to_evidence(
                document,
                used_for=DOCUMENT_EVIDENCE_USED_FOR,
            )
        )

    return dedupe_evidence(evidence_items)


def build_retrieval_state_payload(
    *,
    contexts: dict[Any, list[dict[str, Any]]],
    documents: list[dict[str, Any]],
) -> dict[str, Any]:
    """retrieve_context_node가 state에 합칠 evidence 관련 payload를 만든다."""

    evidence_items = build_retrieval_evidence_items(contexts=contexts, documents=documents)
    return {
        "retrieval_query_plan": build_retrieval_query_plan(contexts),
        "evidence_items": evidence_items,
        "used_sources": build_used_sources(evidence_items),
    }
