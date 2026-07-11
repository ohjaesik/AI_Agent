# app/sources/models.py

"""source/evidence 관련 dataclass 모델.

URL 로드 결과나 source document metadata를 구조화된 객체로 다룰 때 사용한다.
"""

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
    """보고서 citation과 평가에 사용할 표준 evidence item 모델이다."""
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
    """최종 보고서 reference/source 목록에 들어갈 표준 source 모델이다."""
    source_key: str
    source_type: SourceType
    source_name: str
    source_url: str | None
    author_or_org: str | None
    published_date: str | None
    accessed_date: str | None
    citation_label: str