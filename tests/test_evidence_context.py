"""RAG/문서 context를 evidence state payload로 변환하는 로직을 검증한다."""

from app.graph.evidence_context import (
    DOCUMENT_EVIDENCE_USED_FOR,
    RAG_EVIDENCE_USED_FOR,
    build_retrieval_state_payload,
)


def test_build_retrieval_state_payload_dedupes_evidence_and_builds_sources() -> None:
    """중복 RAG chunk를 제거하고 내부 문서까지 used_sources로 변환한다."""

    contexts = {
        "10": [
            {
                "chunk_id": 1,
                "document_id": 100,
                "process_id": 10,
                "title": "업무 매뉴얼",
                "content": "계약 검토 절차",
                "similarity": 0.91,
                "retrieval_query_plan": [{"strategy": "semantic"}],
            },
            {
                "chunk_id": 1,
                "document_id": 100,
                "process_id": 10,
                "title": "업무 매뉴얼",
                "content": "계약 검토 절차",
                "similarity": 0.91,
            },
        ]
    }
    documents = [
        {
            "id": 7,
            "title": "보안 기준서",
            "content": "민감정보 처리 기준",
            "department": "보안팀",
            "process_id": 10,
        }
    ]

    payload = build_retrieval_state_payload(contexts=contexts, documents=documents)

    assert len(payload["evidence_items"]) == 2
    assert len(payload["used_sources"]) == 2
    assert payload["retrieval_query_plan"] == {"10": [{"strategy": "semantic"}]}
    assert payload["evidence_items"][0]["used_for"] == RAG_EVIDENCE_USED_FOR
    assert payload["evidence_items"][1]["used_for"] == DOCUMENT_EVIDENCE_USED_FOR


def test_build_retrieval_state_payload_handles_empty_contexts() -> None:
    """검색 결과가 없어도 내부 문서 evidence와 빈 query plan을 안정적으로 만든다."""

    payload = build_retrieval_state_payload(
        contexts={"10": []},
        documents=[{"id": 1, "title": "내부 정책", "content": "정책 본문"}],
    )

    assert payload["retrieval_query_plan"] == {"10": []}
    assert payload["evidence_items"][0]["source_type"] == "internal_db_document"
