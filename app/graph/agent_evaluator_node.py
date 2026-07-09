# app/graph/agent_evaluator_node.py

from __future__ import annotations

from typing import Any

from app.agents.evaluator import evaluate_agent_outputs
from app.db.crud import save_analysis_result, write_audit_log
from app.db.database import SessionLocal
from app.graph.nodes import append_audit, append_error
from app.graph.state import AXPlannerState


def agent_evaluator_node(state: AXPlannerState) -> dict[str, Any]:
    node_name = "agent_evaluator"

    try:
        result = evaluate_agent_outputs(state)
        updated_priority_ranking = result.get("updated_priority_ranking", state.get("priority_ranking", {}))
        result_without_ranking: dict[str, Any] = {
            "agent_tool_permissions": result.get("agent_tool_permissions", []),
            "items": result.get("items", []),
            "summary": result.get("summary", {}),
        }

        with SessionLocal() as db:
            save_analysis_result(
                db=db,
                project_id=int(state["project_id"]),
                node_name=node_name,
                result_json=result_without_ranking,
            )
            save_analysis_result(
                db=db,
                project_id=int(state["project_id"]),
                node_name="priority_ranking_after_agent_evaluation",
                result_json=updated_priority_ranking,
            )
            write_audit_log(
                db=db,
                project_id=int(state["project_id"]),
                node_name=node_name,
                event_type="success",
                payload=result.get("summary", {}),
            )

        return {
            "agent_evaluation": result_without_ranking,
            "priority_ranking": updated_priority_ranking,
            "audit_logs": append_audit(
                state,
                node_name,
                "success",
                payload=result.get("summary", {}),
            ),
        }

    except Exception as exc:
        return {
            "errors": append_error(state, node_name, exc),
            "audit_logs": append_audit(state, node_name, "failed"),
        }
