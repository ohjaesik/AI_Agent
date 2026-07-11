"""근거 자료를 보고서 citation/source 구조로 바꾸는 standalone helper.

`app/sources/collector.py`와 같은 역할을 하는 보조 모듈이며, 내부 문서, RAG chunk,
Agent 산출물을 모두 동일한 evidence item 형태로 정규화한다. 보고서 생성 단계는
이 구조를 사용해 본문 citation label과 참고자료 목록을 일관되게 만든다.
"""

from __future__ import annotations

from datetime import date
from typing import Any


def make_citation_label(prefix: str, source_id: Any) -> str:
    """보고서 본문에 삽입할 짧은 citation label을 만든다."""
    return f"[{prefix}-{source_id}]"


def internal_document_to_evidence(
    document: dict[str, Any],
    used_for: list[str] | None = None,
) -> dict[str, Any]:
    """DB에서 읽은 내부 문서 record를 evidence item으로 변환한다.

    문서 metadata와 본문 일부를 함께 보존해 RAG 검색 없이도 보고서 근거로 사용할 수
    있게 한다. `used_for`는 어떤 판단 또는 보고서 section에서 사용했는지 추적한다.
    """
    document_id = document.get("id")

    return {
        "evidence_id": f"doc-{document_id}",
        "source_type": "internal_db_document",
        "title": document.get("title", "내부 문서"),
        "content": document.get("content", ""),
        "summary": document.get("content", "")[:500],
        "source_name": document.get("title", "내부 문서"),
        "source_url": None,
        "author_or_org": document.get("department") or "내부 부서",
        "published_date": None,
        "accessed_date": str(date.today()),
        "document_id": document_id,
        "chunk_id": None,
        "process_id": document.get("process_id"),
        "used_for": used_for or ["internal_context"],
        "citation_label": make_citation_label("내부문서", document_id),
        "confidence": 0.9,
        "metadata": {
            "document_type": document.get("document_type"),
            "department": document.get("department"),
            "security_level": document.get("security_level"),
            "contains_sensitive_info": document.get("contains_sensitive_info"),
        },
    }


def rag_chunk_to_evidence(
    chunk: dict[str, Any],
    used_for: list[str] | None = None,
) -> dict[str, Any]:
    """vector search로 찾은 chunk record를 evidence item으로 변환한다.

    chunk similarity를 confidence로 넘겨 이후 evaluator/report 단계가 근거 강도를
    판단할 수 있게 한다.
    """
    chunk_id = chunk.get("chunk_id")
    document_id = chunk.get("document_id")

    return {
        "evidence_id": f"rag-{chunk_id}",
        "source_type": "rag_chunk",
        "title": chunk.get("title", "RAG 검색 문서"),
        "content": chunk.get("content", ""),
        "summary": chunk.get("content", "")[:500],
        "source_name": chunk.get("title", "RAG 검색 문서"),
        "source_url": None,
        "author_or_org": "내부 문서",
        "published_date": None,
        "accessed_date": str(date.today()),
        "document_id": document_id,
        "chunk_id": chunk_id,
        "process_id": chunk.get("process_id"),
        "used_for": used_for or ["rag_context"],
        "citation_label": make_citation_label("RAG", chunk_id),
        "confidence": float(chunk.get("similarity") or 0.0),
        "metadata": {
            "document_type": chunk.get("document_type"),
            "security_level": chunk.get("security_level"),
            "contains_sensitive_info": chunk.get("contains_sensitive_info"),
            "distance": chunk.get("distance"),
            "similarity": chunk.get("similarity"),
        },
    }


def agent_output_to_evidence(
    evidence_id: str,
    title: str,
    content: str,
    used_for: list[str],
    source_agent: str,
) -> dict[str, Any]:
    """Agent가 만든 중간 산출물을 evidence item으로 감싸 downstream에 넘긴다.

    실제 외부 문서가 아니라 Agent 판단 결과를 근거로 남겨야 할 때 사용한다. 이를 통해
    최종 보고서에서 어떤 Agent가 어떤 정보를 만들었는지 추적할 수 있다.
    """
    return {
        "evidence_id": evidence_id,
        "source_type": "agent_output",
        "title": title,
        "content": content,
        "summary": content[:500],
        "source_name": source_agent,
        "source_url": None,
        "author_or_org": source_agent,
        "published_date": None,
        "accessed_date": str(date.today()),
        "document_id": None,
        "chunk_id": None,
        "process_id": None,
        "used_for": used_for,
        "citation_label": f"[Agent-{source_agent}]",
        "confidence": 0.8,
        "metadata": {
            "source_agent": source_agent,
        },
    }


def dedupe_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """동일 evidence가 여러 경로로 들어왔을 때 순서를 유지하면서 중복을 제거한다."""
    seen: set[str] = set()
    result: list[dict[str, Any]] = []

    for item in items:
        key = item.get("evidence_id")

        if not key:
            key = f"{item.get('source_name')}:{item.get('content', '')[:120]}"

        if key in seen:
            continue

        seen.add(key)
        result.append(item)

    return result


def build_used_sources(evidence_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """evidence item 목록에서 보고서 참고자료 목록에 들어갈 source만 추출한다."""
    seen: set[str] = set()
    sources: list[dict[str, Any]] = []

    for item in evidence_items:
        source_key = item.get("source_url") or item.get("source_name") or item.get("title")

        if not source_key or source_key in seen:
            continue

        seen.add(source_key) 

        sources.append(
            {
                "source_key": source_key,
                "source_type": item.get("source_type"),
                "source_name": item.get("source_name") or item.get("title"),
                "source_url": item.get("source_url"),
                "author_or_org": item.get("author_or_org"),
                "published_date": item.get("published_date"),
                "accessed_date": item.get("accessed_date"),
                "citation_label": item.get("citation_label"),
            }
        )

    return sources
