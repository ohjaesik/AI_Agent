"""LLM JSON prompt/response 공통 유틸리티를 검증한다."""

import pytest

from app.core.llm_json import compact_json, extract_json_object, strip_json_fence


def test_compact_json_serializes_korean_context_and_truncates() -> None:
    """한글 context를 유지하면서 prompt 길이 상한을 넘으면 말줄임 처리한다."""

    compacted = compact_json({"목표": "근거 기반 AX 추천", "본문": "가" * 50}, max_chars=30)

    assert "목표" in compacted
    assert compacted.endswith("...")
    assert len(compacted) == 33


def test_strip_json_fence_removes_markdown_wrapper() -> None:
    """모델이 붙인 ```json fence를 제거해 JSON parser가 읽을 수 있게 한다."""

    assert strip_json_fence('```json\n{"ok": true}\n```') == '{"ok": true}'


def test_extract_json_object_accepts_raw_fenced_and_explained_json() -> None:
    """순수 JSON, fenced JSON, 설명이 섞인 JSON object를 모두 같은 dict로 복구한다."""

    assert extract_json_object('{"route_hint": "continue"}') == {"route_hint": "continue"}
    assert extract_json_object('```json\n{"route_hint": "continue"}\n```') == {"route_hint": "continue"}
    assert extract_json_object('결과입니다.\n{"route_hint": "continue"}\n확인하세요.') == {
        "route_hint": "continue"
    }


def test_extract_json_object_rejects_non_object_payload() -> None:
    """array/string 같은 비-object 응답은 fallback 경로로 넘어가도록 예외를 낸다."""

    with pytest.raises(ValueError, match="Supervisor LLM response JSON must be an object"):
        extract_json_object("[1, 2, 3]", object_name="Supervisor LLM response JSON")
