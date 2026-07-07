# app/sources/models.py

from __future__ import annotations

from typing import Any, Literal, TypedDict


SourceType = Literal[
    "user_upload",
    "internal_db_document",
    "rag_chunk",
    "web_research",
    "agent_output",
]


class EvidenceItem(TypedDict, total=False):
    evidence_id: str
    source_type: SourceType

    title: str
    content: str
    summary: str

    source_name: str
    source_url: str | None
    author_or_org: str | None
    published_date: str | None
    accessed_date: str | None

    document_id: int | None
    chunk_id: int | None
    process_id: int | None

    used_for: list[str]
    citation_label: str
    confidence: float

    metadata: dict[str, Any]


class UsedSource(TypedDict, total=False):
    source_key: str
    source_type: SourceType
    source_name: str
    source_url: str | None
    author_or_org: str | None
    published_date: str | None
    accessed_date: str | None
    citation_label: str