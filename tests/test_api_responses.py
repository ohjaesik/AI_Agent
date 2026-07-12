"""프론트가 의존하는 API 응답 payload shape을 검증한다."""

from __future__ import annotations

from app.api.responses import build_analysis_response
from app.security.access_control import AccessContext


def test_build_analysis_response_keeps_success_and_trace_fields() -> None:
    result = {
        "report_docx_path": "outputs/report.docx",
        "report_data": {
            "generation": {"mode": "deterministic"},
            "citation_validation": {"valid": True},
        },
        "priority_ranking": {"items": [{"rank": 1}, {"rank": 2}, {"rank": 3}, {"rank": 4}, {"rank": 5}, {"rank": 6}]},
        "compliance_assessment": {"summary": {"blocked_count": 0}},
        "agent_model_decisions": [{"model": str(idx)} for idx in range(12)],
        "agent_supervisor_delegations": [{"stage": str(idx)} for idx in range(12)],
        "agent_autonomy_loop_decisions": [{"decision": str(idx)} for idx in range(12)],
        "total_cost_summary": {"estimated_total_cost_usd": 0.12},
    }

    response = build_analysis_response(result, AccessContext(user_id="u1", role="admin"))

    assert response["status"] == "ok"
    assert response["access"] == {"user_id": "u1", "role": "admin"}
    assert response["report_docx_path"] == "outputs/report.docx"
    assert response["citation_validation"] == {"valid": True}
    assert len(response["top_candidates"]) == 5
    assert response["model_decisions"][0] == {"model": "2"}
    assert response["supervisor_delegations"][0] == {"stage": "2"}
    assert response["autonomy_loop_decisions"][0] == {"decision": "2"}


def test_build_analysis_response_marks_interrupt_without_access_payload() -> None:
    result = {
        "__interrupt__": [{"value": {"reason": "review"}}],
        "priority_ranking": {"items": [{"rank": 1}]},
    }

    response = build_analysis_response(result, AccessContext(user_id="u1", role="manager"))

    assert response["status"] == "interrupted"
    assert "review" in response["interrupt"]
    assert "access" not in response
    assert response["top_candidates"] == [{"rank": 1}]
