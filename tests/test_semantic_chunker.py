"""semantic similarity chunker가 의미 경계와 metadata를 유지하는지 검증한다.
"""

from __future__ import annotations

from app.rag.chunker import chunk_text


def test_semantic_chunker_preserves_strategy_metadata() -> None:
    text = (
        "고객 상담 업무는 제품 추천과 문의 응답을 반복한다. 상담원은 제품 정보와 구매 이력을 함께 확인한다.\n"
        "물류 운영 업무는 재고 이동과 배송 예외를 추적한다. 담당자는 운송장과 창고 데이터를 대조한다.\n"
        "보안 검토 업무는 접근 권한과 감사 로그를 확인한다. 담당자는 승인 이력과 정책 문서를 비교한다."
    )

    chunks = chunk_text(
        text,
        chunk_size=120,
        chunk_overlap=20,
        strategy="semantic",
        semantic_similarity_threshold=0.18,
        semantic_min_chunk_chars=60,
    )

    assert len(chunks) >= 2
    assert all(chunk.metadata["chunk_strategy"] == "semantic_similarity" for chunk in chunks)
    assert all("chunk_boundary_reason" in chunk.metadata for chunk in chunks)


def test_recursive_chunker_can_still_be_selected() -> None:
    chunks = chunk_text(
        "A short paragraph. Another short paragraph.",
        chunk_size=20,
        chunk_overlap=5,
        strategy="recursive",
    )

    assert chunks
    assert all(chunk.metadata["chunk_strategy"] == "recursive" for chunk in chunks)
