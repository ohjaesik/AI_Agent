"""Graph audit/error trace 공통 helper를 검증한다."""

from app.graph.audit import append_audit, append_error


def test_append_audit_preserves_existing_logs_and_adds_standard_payload() -> None:
    """기존 audit log 뒤에 node/status/timestamp/payload 형식의 기록을 추가한다."""

    state = {"audit_logs": [{"node": "previous", "status": "success"}]}

    logs = append_audit(state, "retrieve_context", "success", {"chunk_count": 10})

    assert logs[0]["node"] == "previous"
    assert logs[1]["node"] == "retrieve_context"
    assert logs[1]["status"] == "success"
    assert logs[1]["payload"] == {"chunk_count": 10}
    assert "timestamp" in logs[1]


def test_append_error_preserves_existing_errors_and_includes_exception_type() -> None:
    """오류 trace에는 node명, 예외 타입, 예외 메시지를 함께 남긴다."""

    errors = append_error({"errors": ["old"]}, "roi_cost", ValueError("bad input"))

    assert errors == ["old", "[roi_cost] ValueError: bad input"]
