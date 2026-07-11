# app/rag/chunker.py
"""RAG 색인용 문서 chunking 로직을 제공한다.

기본 전략은 `semantic_similarity`다. 문서를 줄/문장 단위로 나눈 뒤, 인접 단위의
단어/2-gram cosine 유사도가 낮아지는 지점을 topic boundary로 보고 chunk를 끊는다.

왜 embedding 기반 semantic chunker를 쓰지 않는가:
- 문장마다 embedding을 만들면 색인 비용과 시간이 크게 늘어난다.
- 이 프로젝트의 목적은 "완벽한 의미 분할"보다 "문장 경계를 보존하면서 RAG 근거를
  안정적으로 찾는 것"이다.
- 그래서 비용 없는 lexical similarity를 사용하고, 너무 긴 단위만 recursive fallback한다.

각 chunk metadata에는 전략, boundary reason, threshold, overlap 같은 값을 남겨
나중에 workflow_state/DB에서 어떤 방식으로 잘렸는지 추적할 수 있게 한다.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:
    RecursiveCharacterTextSplitter = None


@dataclass(frozen=True)
class TextChunk:
    """DB에 저장할 chunk 한 조각과 metadata를 담는 값 객체."""

    chunk_index: int
    content: str
    metadata: dict[str, Any]


DEFAULT_CHUNK_STRATEGY = "semantic"
DEFAULT_SEMANTIC_SIMILARITY_THRESHOLD = 0.16
DEFAULT_SEMANTIC_MIN_CHUNK_CHARS = 360
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9가-힣]{2,}")
SENTENCE_BOUNDARY_PATTERN = re.compile(
    r"(?<=[.!?。！？])\s+|(?<=다\.)\s+|(?<=요\.)\s+|(?<=니다\.)\s+|(?<=음\.)\s+|(?<=함\.)\s+"
)


def normalize_text(text: str) -> str:
    """
    문서 텍스트의 기본 공백을 정리한다.
    너무 강하게 정리하면 문서 구조가 깨질 수 있으므로 최소한만 처리한다.
    """
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def get_text_splitter(
    chunk_size: int = 800,
    chunk_overlap: int = 120,
) -> Any:
    """
    LangChain 공식 문서 기준 일반 텍스트 분할에는 RecursiveCharacterTextSplitter를 사용한다.
    한국어 문서도 문단/줄바꿈/문장 단위가 어느 정도 유지되도록 separator를 명시한다.
    """
    if RecursiveCharacterTextSplitter is None:
        return None

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


def fallback_recursive_split_text(
    text: str,
    chunk_size: int,
    chunk_overlap: int,
) -> list[str]:
    """langchain_text_splitters가 없을 때 쓰는 최소 fallback splitter.

    외부 의존성이 없는 환경에서도 색인이 중단되지 않게 하기 위한 안전장치다.
    문단/줄/문장/공백 순서로 가능한 마지막 separator를 찾아 너무 어색한 중간 절단을
    줄이고, overlap을 적용해 검색 문맥이 완전히 끊기지 않게 한다.
    """

    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    separators = ["\n\n", "\n", "다. ", ". ", " ", ""]

    while start < len(text):
        hard_end = min(len(text), start + chunk_size)
        window = text[start:hard_end]
        split_end = len(window)

        for separator in separators:
            if not separator:
                continue
            position = window.rfind(separator)
            if position >= int(chunk_size * 0.45):
                split_end = position + len(separator)
                break

        if split_end <= 0:
            split_end = len(window)

        chunk = text[start : start + split_end].strip()
        if chunk:
            chunks.append(chunk)

        if hard_end >= len(text):
            break

        next_start = start + split_end - max(0, chunk_overlap)
        start = max(start + 1, next_start)

    return chunks


def chunk_text(
    text: str,
    base_metadata: dict[str, Any] | None = None,
    chunk_size: int = 800,
    chunk_overlap: int = 120,
    strategy: str = DEFAULT_CHUNK_STRATEGY,
    semantic_similarity_threshold: float = DEFAULT_SEMANTIC_SIMILARITY_THRESHOLD,
    semantic_min_chunk_chars: int = DEFAULT_SEMANTIC_MIN_CHUNK_CHARS,
) -> list[TextChunk]:
    """문서 텍스트를 지정 전략에 따라 TextChunk 목록으로 변환한다.

    외부에서 호출하는 대표 진입점이다. `strategy`가 semantic 계열이면
    `semantic_similarity_chunk_text`를 사용하고, 그 외에는 recursive splitter로
    되돌린다. 빈 문서는 빈 목록을 반환해 downstream 색인 로직이 자연스럽게 skip한다.
    """

    normalized = normalize_text(text)

    if not normalized:
        return []

    strategy = str(strategy or DEFAULT_CHUNK_STRATEGY).lower()
    if strategy in {"semantic", "similarity", "semantic_similarity"}:
        return semantic_similarity_chunk_text(
            normalized=normalized,
            base_metadata=base_metadata or {},
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            semantic_similarity_threshold=semantic_similarity_threshold,
            semantic_min_chunk_chars=semantic_min_chunk_chars,
        )

    return recursive_chunk_text(
        normalized=normalized,
        base_metadata=base_metadata or {},
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        strategy=strategy,
    )


def recursive_chunk_text(
    *,
    normalized: str,
    base_metadata: dict[str, Any],
    chunk_size: int,
    chunk_overlap: int,
    strategy: str = "recursive",
) -> list[TextChunk]:
    """기존 고정 크기 recursive chunking 경로.

    semantic 방식이 맞지 않는 문서나 fallback 상황에서 사용한다. metadata의
    `chunk_strategy`와 `chunk_boundary_reason`을 남겨 semantic chunk와 구분한다.
    """

    splitter = get_text_splitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    if splitter is not None:
        chunks = splitter.split_text(normalized)
    else:
        chunks = fallback_recursive_split_text(normalized, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
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
                    "chunk_strategy": strategy,
                    "chunk_boundary_reason": "recursive_character_split",
                },
            )
        )

    return result


def split_semantic_units(normalized: str) -> list[str]:
    """문단/문장/목록 단위를 최대한 보존하며 의미 단위 후보를 만든다.

    별도 형태소 분석기나 embedding을 쓰지 않기 때문에 빠르고 비용이 없다.
    긴 줄은 문장 경계로 한 번 더 나누고, 그래도 긴 단위는 recursive fallback이
    뒤에서 처리한다.
    """

    units: list[str] = []
    for line in normalized.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        sentence_parts = [part.strip() for part in SENTENCE_BOUNDARY_PATTERN.split(stripped) if part.strip()]
        if len(sentence_parts) <= 1:
            units.append(stripped)
        else:
            units.extend(sentence_parts)
    return units


def text_terms(text: str) -> Counter[str]:
    """짧은 한국어/영문 텍스트의 유사도 계산용 term vector를 만든다."""

    tokens = [token.lower() for token in TOKEN_PATTERN.findall(text)]
    terms: Counter[str] = Counter(tokens)
    for left, right in zip(tokens, tokens[1:], strict=False):
        terms[f"{left} {right}"] += 1
    return terms


def cosine_similarity(left: Counter[str], right: Counter[str]) -> float:
    """두 term vector의 cosine similarity를 계산한다."""

    if not left or not right:
        return 0.0

    shared = set(left) & set(right)
    numerator = sum(left[item] * right[item] for item in shared)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))

    if left_norm <= 0 or right_norm <= 0:
        return 0.0

    return numerator / (left_norm * right_norm)


def recent_unit_text(units: list[str], max_units: int = 2) -> str:
    """현재 chunk 끝부분만 뽑아 다음 문장과의 topic continuity를 비교한다."""

    return " ".join(units[-max_units:])


def join_units(units: list[str]) -> str:
    """의미 단위 목록을 chunk 본문으로 합친다."""

    return "\n".join(unit.strip() for unit in units if unit.strip()).strip()


def semantic_tail_overlap(units: list[str], chunk_overlap: int) -> list[str]:
    """다음 chunk에 붙일 overlap을 문장 단위로 고른다."""

    if chunk_overlap <= 0:
        return []

    selected: list[str] = []
    current_chars = 0
    for unit in reversed(units):
        unit_len = len(unit)
        if selected and current_chars + unit_len > chunk_overlap:
            break
        selected.append(unit)
        current_chars += unit_len
        if current_chars >= chunk_overlap:
            break
    return list(reversed(selected))


def make_semantic_chunk(
    *,
    index: int,
    units: list[str],
    base_metadata: dict[str, Any],
    chunk_size: int,
    chunk_overlap: int,
    semantic_similarity_threshold: float,
    semantic_min_chunk_chars: int,
    boundary_reason: str,
) -> TextChunk | None:
    """현재까지 모은 의미 단위를 하나의 semantic chunk로 만든다."""

    content = join_units(units)
    if not content:
        return None
    return TextChunk(
        chunk_index=index,
        content=content,
        metadata={
            **base_metadata,
            "chunk_index": index,
            "chunk_size": len(content),
            "chunk_strategy": "semantic_similarity",
            "semantic_unit_count": len(units),
            "semantic_similarity_threshold": semantic_similarity_threshold,
            "semantic_min_chunk_chars": semantic_min_chunk_chars,
            "semantic_target_chunk_chars": chunk_size,
            "semantic_overlap_chars": chunk_overlap,
            "chunk_boundary_reason": boundary_reason,
        },
    )


def split_oversized_unit(
    *,
    unit: str,
    base_metadata: dict[str, Any],
    chunk_size: int,
    chunk_overlap: int,
    start_index: int,
) -> list[TextChunk]:
    """표/긴 문단처럼 단일 의미 단위가 너무 길 때만 recursive fallback을 쓴다."""

    fallback_chunks = recursive_chunk_text(
        normalized=unit,
        base_metadata=base_metadata,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        strategy="semantic_oversized_unit_recursive_fallback",
    )
    result: list[TextChunk] = []
    for offset, chunk in enumerate(fallback_chunks):
        result.append(
            TextChunk(
                chunk_index=start_index + offset,
                content=chunk.content,
                metadata={
                    **chunk.metadata,
                    "chunk_index": start_index + offset,
                    "chunk_boundary_reason": "oversized_semantic_unit",
                },
            )
        )
    return result


def semantic_similarity_chunk_text(
    *,
    normalized: str,
    base_metadata: dict[str, Any],
    chunk_size: int,
    chunk_overlap: int,
    semantic_similarity_threshold: float,
    semantic_min_chunk_chars: int,
) -> list[TextChunk]:
    """문장 의미 단위와 인접 유사도로 topic boundary를 찾는 chunker.

    비용이 큰 sentence embedding은 사용하지 않는다. 대신 단어/2-gram cosine
    유사도로 인접 의미 단위가 같은 주제인지 판단한다. 이 방식은 완전한
    semantic embedding chunker보다 가볍지만, 고정 글자 수 split보다 문장
    경계를 훨씬 잘 보존한다.
    """

    units = split_semantic_units(normalized)
    if not units:
        return []

    safe_chunk_size = max(240, int(chunk_size or 800))
    safe_min_chars = max(120, min(int(semantic_min_chunk_chars or DEFAULT_SEMANTIC_MIN_CHUNK_CHARS), safe_chunk_size))
    threshold = max(0.0, min(float(semantic_similarity_threshold), 0.95))

    result: list[TextChunk] = []
    current_units: list[str] = []
    last_boundary_reason = "document_end"

    def flush(reason: str) -> None:
        """현재 누적 단위를 chunk로 확정하고 overlap 단위만 남긴다."""

        nonlocal current_units, last_boundary_reason
        chunk = make_semantic_chunk(
            index=len(result),
            units=current_units,
            base_metadata=base_metadata,
            chunk_size=safe_chunk_size,
            chunk_overlap=chunk_overlap,
            semantic_similarity_threshold=threshold,
            semantic_min_chunk_chars=safe_min_chars,
            boundary_reason=reason,
        )
        if chunk is not None:
            result.append(chunk)
        overlap_units = semantic_tail_overlap(current_units, chunk_overlap)
        current_units = overlap_units
        last_boundary_reason = reason

    for unit in units:
        unit = unit.strip()
        if not unit:
            continue

        if len(unit) > safe_chunk_size and not current_units:
            fallback = split_oversized_unit(
                unit=unit,
                base_metadata=base_metadata,
                chunk_size=safe_chunk_size,
                chunk_overlap=chunk_overlap,
                start_index=len(result),
            )
            result.extend(fallback)
            current_units = []
            last_boundary_reason = "oversized_semantic_unit"
            continue

        current_text = join_units(current_units)
        candidate_text = join_units([*current_units, unit])
        current_len = len(current_text)
        candidate_len = len(candidate_text)

        if current_units and current_len >= safe_min_chars:
            similarity = cosine_similarity(text_terms(recent_unit_text(current_units)), text_terms(unit))
            topic_shift = similarity < threshold
            size_overflow = candidate_len > safe_chunk_size

            if size_overflow or topic_shift:
                # 크기가 넘치거나 인접 문장과의 유사도가 급격히 낮으면 chunk를 확정한다.
                # boundary_reason은 나중에 검색 품질을 볼 때 어떤 이유로 잘렸는지 확인하는 힌트다.
                flush("size_overflow" if size_overflow else "low_adjacent_similarity")

        if len(unit) > safe_chunk_size and not current_units:
            fallback = split_oversized_unit(
                unit=unit,
                base_metadata=base_metadata,
                chunk_size=safe_chunk_size,
                chunk_overlap=chunk_overlap,
                start_index=len(result),
            )
            result.extend(fallback)
            current_units = []
            last_boundary_reason = "oversized_semantic_unit"
            continue

        current_units.append(unit)

    if current_units:
        chunk = make_semantic_chunk(
            index=len(result),
            units=current_units,
            base_metadata=base_metadata,
            chunk_size=safe_chunk_size,
            chunk_overlap=chunk_overlap,
            semantic_similarity_threshold=threshold,
            semantic_min_chunk_chars=safe_min_chars,
            boundary_reason=last_boundary_reason if last_boundary_reason != "document_end" else "document_end",
        )
        if chunk is not None:
            result.append(chunk)

    return result
