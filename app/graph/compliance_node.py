# app/graph/compliance_node.py

"""LangGraph에서 compliance assessment를 실행하는 node.

risk governance 결과와 업무 후보를 바탕으로 blocked/human review/control 정보를 state에
저장한다.
"""

from __future__ import annotations

from typing import Any

from app.compliance.assessment import assess_ai_compliance
from app.db.crud import save_analysis_result, write_audit_log
from app.db.database import SessionLocal
from app.graph.audit import append_audit, append_error
from app.graph.state import AXPlannerState


def compliance_assessment_node(state: AXPlannerState) -> dict[str, Any]:
    """risk governance 결과를 compliance level과 review/control 항목으로 변환한다."""
    node_name = "compliance_assessment"

    try:
        result = assess_ai_compliance(
            processes=state.get("business_processes", []),
            risk_governance=state.get("risk_governance"),
        )
        risk_governance = dict(state.get("risk_governance") or {})
        risk_governance["compliance_assessment"] = result

        with SessionLocal() as db:
            save_analysis_result(
                db=db,
                project_id=int(state["project_id"]),
                node_name=node_name,
                result_json=result,
            )
            write_audit_log(
                db=db,
                project_id=int(state["project_id"]),
                node_name=node_name,
                event_type="success",
                payload=result.get("summary", {}),
            )

        return {
            "compliance_assessment": result,
            "risk_governance": risk_governance,
            "audit_logs": append_audit(
                state,
                node_name,
                "success",
                payload={
                    "overall_status": result.get("overall_status"),
                    **result.get("summary", {}),
                },
            ),
        }

    except Exception as exc:
        return {
            "errors": append_error(state, node_name, exc),
            "audit_logs": append_audit(state, node_name, "failed"),
        }
