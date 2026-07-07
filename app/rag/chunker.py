# app/rag/chunker.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter


@dataclass(frozen=True)
class TextChunk:
    chunk_index: int
    content: str
    metadata: dict[str, Any]


def normalize_text(text: str) -> str:
    """
    문서 텍스트의 기본 공백을 정리한다.
    너무 강하게 정리하면 문서 구조가 깨질 수 있으므로 최소한만 처리한다.
    """
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def get_text_splitter(
    chunk_size: int = 800,
    chunk_overlap: int = 120,
) -> RecursiveCharacterTextSplitter:
    """
    LangChain 공식 문서 기준 일반 텍스트 분할에는 RecursiveCharacterTextSplitter를 사용한다.
    한국어 문서도 문단/줄바꿈/문장 단위가 어느 정도 유지되도록 separator를 명시한다.
    """
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        is_separator_regex=False,
        separators=[
            "\n\n",
            "\n",
            "다. ",
            ". ",
            " ",
            "",
        ],
    )


def chunk_text(
    text: str,
    base_metadata: dict[str, Any] | None = None,
    chunk_size: int = 800,
    chunk_overlap: int = 120,
) -> list[TextChunk]:
    normalized = normalize_text(text)

    if not normalized:
        return []

    splitter = get_text_splitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    chunks = splitter.split_text(normalized)
    base_metadata = base_metadata or {}

    result: list[TextChunk] = []

    for idx, chunk in enumerate(chunks):
        cleaned = chunk.strip()

        if not cleaned:
            continue

        result.append(
            TextChunk(
                chunk_index=idx,
                content=cleaned,
                metadata={
                    **base_metadata,
                    "chunk_index": idx,
                    "chunk_size": len(cleaned),
                },
            )
        )

    return result