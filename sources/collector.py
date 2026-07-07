# app/sources/collector.py

from __future__ import annotations

from datetime import date
from typing import Any


def make_citation_label(prefix: str, source_id: Any) -> str:
    return f"[{prefix}-{source_id}]"


def internal_document_to_evidence(
    document: dict[str, Any],
    used_for: list[str] | None = None,
) -> dict[str, Any]:
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