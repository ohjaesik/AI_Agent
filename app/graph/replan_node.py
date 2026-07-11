# app/graph/replan_node.py

"""근거 부족 후보에 대해 bounded replan을 수행하는 LangGraph node.

정책 판단은 `replan_policy.py`, 실제 source 수집/색인은 `replan_sources.py`에 두고
이 파일은 graph node로서 실행 순서, DB 저장, audit/error trace만 담당한다.
"""

from __future__ import annotations

from typing import Any

from app.db.crud import save_analysis_result, write_audit_log
from app.db.database import SessionLocal
from app.graph.audit import append_audit, append_error
from app.graph.replan_policy import (
    build_replan_items,
    build_replan_request,
    build_stopped_replan_request,
    current_replan_attempts,
    decide_replan_route_reason,
    has_additional_evidence_need,
    max_replan_attempts,
    previous_replan_unproductive,
    should_continue_after_replan,
    source_collection_productive,
    stop_reason_before_source_collection,
)
from app.graph.replan_sources import collect_discovered_sources, has_replan_source_path
from app.graph.state import AXPlannerState


def replan_route_reason(state: AXPlannerState) -> str:
    """evaluation 결과와 replan guard를 보고 route reason을 계산한다."""

    return decide_replan_route_reason(
        attempts=current_replan_attempts(state),
        max_attempts_value=max_replan_attempts(),
        additional_evidence_needed=has_additional_evidence_need(state),
        previous_unproductive=previous_replan_unproductive(state),
        has_source_path=has_replan_source_path(state),
    )


def should_replan(state: AXPlannerState) -> str:
    """evaluation 결과와 replan guard를 보고 agent_replan으로 갈지 delivery로 갈지 결정한다."""

    return "agent_replan" if replan_route_reason(state) == "route_to_replan" else "human_review"


def build_replan_audit_payload(
    *,
    attempts: int,
    max_attempts_value: int,
    route_after_replan: str,
    stop_reason: str | None,
    replan_items: list[dict[str, Any]],
    source_collection: dict[str, Any],
) -> dict[str, Any]:
    """DB audit와 in-memory audit에 공통으로 남길 replan 실행 요약을 만든다."""

    return {
        "attempt": attempts,
        "max_attempts": max_attempts_value,
        "route_after_replan": route_after_replan,
        "stop_reason": stop_reason,
        "replan_item_count": len(replan_items),
        "same_domain_url_count": len(source_collection.get("same_domain_discovered", [])),
        "public_web_url_count": len(source_collection.get("public_web_search", {}).get("results", [])),
        "indexed_chunks": source_collection.get("indexed_chunks", 0),
    }


def agent_replan_node(state: AXPlannerState) -> dict[str, Any]:
    """공식자료/선택적 public web search 기반 보강 루프를 실행한다."""

    node_name = "agent_replan"

    try:
        current_attempts = current_replan_attempts(state)
        max_attempts_value = max_replan_attempts()
        stop_reason = stop_reason_before_source_collection(current_attempts, max_attempts_value)

        if stop_reason:
            replan_request = build_stopped_replan_request(current_attempts, max_attempts_value, stop_reason)
            return {
                "replan_attempts": current_attempts,
                "replan_request": replan_request,
                "audit_logs": append_audit(
                    state,
                    node_name,
                    "skipped",
                    payload={"attempt": current_attempts, "max_attempts": max_attempts_value, "reason": stop_reason},
                ),
            }

        attempts = current_attempts + 1
        replan_items = build_replan_items(state)
        source_collection = collect_discovered_sources(state, replan_items=replan_items, max_total=3)
        replan_request = build_replan_request(
            attempts=attempts,
            max_attempts_value=max_attempts_value,
            replan_items=replan_items,
            source_collection=source_collection,
        )
        audit_payload = build_replan_audit_payload(
            attempts=attempts,
            max_attempts_value=max_attempts_value,
            route_after_replan=str(replan_request.get("route_after_replan")),
            stop_reason=replan_request.get("stop_reason"),
            replan_items=replan_items,
            source_collection=source_collection,
        )

        with SessionLocal() as db:
            save_analysis_result(
                db=db,
                project_id=int(state["project_id"]),
                node_name=node_name,
                result_json=replan_request,
            )
            write_audit_log(
                db=db,
                project_id=int(state["project_id"]),
                node_name=node_name,
                event_type="success",
                payload=audit_payload,
            )

        return {
            "replan_attempts": attempts,
            "replan_request": replan_request,
            "audit_logs": append_audit(
                state,
                node_name,
                "success",
                payload=audit_payload,
            ),
        }

    except Exception as exc:
        return {
            "errors": append_error(state, node_name, exc),
            "audit_logs": append_audit(state, node_name, "failed"),
        }


__all__ = [
    "agent_replan_node",
    "build_replan_items",
    "current_replan_attempts",
    "has_replan_source_path",
    "replan_route_reason",
    "should_continue_after_replan",
    "should_replan",
    "source_collection_productive",
]
