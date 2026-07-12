"""API response 조립 helper.

라우트 함수 안에서 workflow state를 직접 잘라내면 endpoint가 길어지고, 성공/interrupt
응답의 필드가 쉽게 어긋난다. 이 모듈은 UI가 공통으로 쓰는 analysis 응답 shape을
한곳에서 만든다.
"""

from __future__ import annotations

from typing import Any

from app.security.access_control import AccessContext


def build_analysis_response(result: dict[str, Any], access: AccessContext) -> dict[str, Any]:
    """Supervisor graph 실행 결과를 프론트가 바로 표시할 수 있는 JSON으로 축약한다."""

    report_data = result.get("report_data") or {}
    payload: dict[str, Any] = {
        "status": "interrupted" if "__interrupt__" in result else "ok",
        "report_docx_path": result.get("report_docx_path"),
        "generation": report_data.get("generation", {}),
        "report_data": report_data,
        "citation_validation": report_data.get("citation_validation", {}),
        "top_candidates": (result.get("priority_ranking") or {}).get("items", [])[:5],
        "compliance_summary": (result.get("compliance_assessment") or {}).get("summary", {}),
        "model_decisions": result.get("agent_model_decisions", [])[-10:],
        "total_cost_summary": result.get("total_cost_summary", {}),
        "supervisor_delegations": result.get("agent_supervisor_delegations", [])[-10:],
        "supervisor_autonomy_policy": result.get("supervisor_autonomy_policy", {}),
        "autonomy_loop_decisions": result.get("agent_autonomy_loop_decisions", [])[-10:],
        "errors": result.get("errors", []),
    }

    if "__interrupt__" in result:
        payload["interrupt"] = str(result.get("__interrupt__"))
    else:
        payload["access"] = {"user_id": access.user_id, "role": access.role}

    return payload
