# app/graph/llm_critic_node.py

from __future__ import annotations

from typing import Any

from app.agents.llm_critic import apply_llm_critic_to_evaluation
from app.agents.model_router import select_agent_model
from app.agents.tool_guard import assert_tools_allowed
from app.db.crud import save_analysis_result, write_audit_log
from app.db.database import SessionLocal
from app.graph.nodes import append_audit, append_error
from app.graph.state import AXPlannerState


def llm_critic_node(state: AXPlannerState) -> dict[str, Any]:
    node_name = "llm_critic"

    try:
        assert_tools_allowed(
            "evaluation_critic_agent",
            ["LLM critic", "quality gate"],
        )
        # LLM Critic 내부 호출은 후보 수, 평가 결과, 근거량을 기준으로
        # Supervisor 모델 라우터가 고른 모델을 사용한다.
        model_assignment = select_agent_model(
            agent_id="evaluation_critic_agent",
            stage_name=node_name,
            call_kind="tool_llm_critic",
            state=state,
        )
        result = apply_llm_critic_to_evaluation(
            priority_ranking=state.get("priority_ranking", {}) or {},
            agent_evaluation=state.get("agent_evaluation", {}) or {},
            model_assignment=model_assignment,
        )
        agent_evaluation = result.get("agent_evaluation", {})
        priority_ranking = result.get("priority_ranking", {})

        with SessionLocal() as db:
            save_analysis_result(
                db=db,
                project_id=int(state["project_id"]),
                node_name=node_name,
                result_json=agent_evaluation,
            )
            save_analysis_result(
                db=db,
                project_id=int(state["project_id"]),
                node_name="priority_ranking_after_llm_critic",
                result_json=priority_ranking,
            )
            write_audit_log(
                db=db,
                project_id=int(state["project_id"]),
                node_name=node_name,
                event_type="success",
                payload=agent_evaluation.get("summary", {}),
            )

        return {
            "agent_evaluation": agent_evaluation,
            "priority_ranking": priority_ranking,
            "agent_model_decisions": [model_assignment],
            "audit_logs": append_audit(
                state,
                node_name,
                "success",
                payload={
                    **(agent_evaluation.get("summary", {}) or {}),
                    "model_provider": model_assignment.get("provider"),
                    "model": model_assignment.get("model"),
                },
            ),
        }

    except Exception as exc:
        return {
            "errors": append_error(state, node_name, exc),
            "audit_logs": append_audit(state, node_name, "failed"),
        }
