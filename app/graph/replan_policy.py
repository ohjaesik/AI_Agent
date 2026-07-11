# app/graph/replan_policy.py
"""근거 보강 replan의 attempt, route, request payload 정책을 담당한다.

`replan_node.py`는 LangGraph node라 DB 저장, audit, source 수집 실행까지 다뤄야 한다.
반면 이 파일은 외부 I/O 없이 "replan을 해야 하는가", "어디로 route할 것인가",
"workflow_state에 어떤 replan_request를 남길 것인가"만 계산한다.
"""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings


REPLAN_MAX_ITEMS = 5
REPLAN_MODE_STOPPED = "stopped_before_source_collection"
REPLAN_MODE_SOURCE_DISCOVERY = "official_domain_plus_opt_in_public_web_discovery"


def build_replan_items(state: dict[str, Any]) -> list[dict[str, Any]]:
    """추가 근거가 필요한 후보를 replan 실행 단위로 변환한다."""

    items: list[dict[str, Any]] = []
    ranking_items = {
        int(item.get("process_id") or 0): item
        for item in state.get("priority_ranking", {}).get("items", [])
    }

    for evaluation in state.get("agent_evaluation", {}).get("items", []):
        if not evaluation.get("requires_additional_evidence"):
            continue
        process_id = int(evaluation.get("process_id") or 0)
        candidate = ranking_items.get(process_id, {})
        items.append(
            {
                "process_id": process_id,
                "candidate_agent_name": evaluation.get("candidate_agent_name") or candidate.get("candidate_agent_name"),
                "process_name": candidate.get("process_name"),
                "evidence_coverage": evaluation.get("evidence_coverage"),
                "confidence_score": evaluation.get("confidence_score"),
                "issues": evaluation.get("issues", []),
                "suggested_actions": [
                    "관련 공식 URL 자동 탐색 및 수집",
                    "옵션 활성화 시 public web search 기반 보조 출처 탐색",
                    "업무 매뉴얼 또는 내부 규정 문서 업로드",
                    "해당 업무 owner 인터뷰 메모 추가",
                    "RAG 재색인 후 재평가",
                ],
                "requery_terms": [
                    candidate.get("process_name"),
                    candidate.get("candidate_agent_name"),
                    candidate.get("target_user"),
                    "업무 절차",
                    "규정",
                    "SOP",
                ],
            }
        )
    return items[:REPLAN_MAX_ITEMS]


def current_replan_attempts(state: dict[str, Any]) -> int:
    """state의 replan_attempts와 replan_request.attempt 중 더 최신 attempt를 읽는다."""

    state_attempts = int(state.get("replan_attempts", 0) or 0)
    request_attempts = int((state.get("replan_request") or {}).get("attempt", 0) or 0)
    return max(state_attempts, request_attempts)


def max_replan_attempts() -> int:
    """환경설정의 replan 최대 시도 횟수를 0 이상으로 정규화한다."""

    return max(int(get_settings().agent_replan_max_attempts or 0), 0)


def has_additional_evidence_need(state: dict[str, Any]) -> bool:
    """Evaluator/Critic summary가 추가 근거 필요 후보를 보고했는지 판단한다."""

    evaluation = state.get("agent_evaluation", {}) or {}
    summary = evaluation.get("summary", {}) or {}
    return int(summary.get("additional_evidence_required_count", 0) or 0) > 0


def source_collection_productive(source_collection: dict[str, Any]) -> bool:
    """source 수집 결과가 retrieval 재실행 가치가 있는지 판단한다."""

    same_domain = source_collection.get("same_domain_discovered") or []
    public_results = ((source_collection.get("public_web_search") or {}).get("results") or [])
    loaded = source_collection.get("loaded") or []
    indexed_chunks = int(source_collection.get("indexed_chunks") or 0)
    return bool(same_domain or public_results or loaded or indexed_chunks > 0)


def previous_replan_unproductive(state: dict[str, Any]) -> bool:
    """이전 replan이 아무 출처/문서/chunk도 만들지 못했으면 반복하지 않는다."""

    if current_replan_attempts(state) <= 0:
        return False
    source_collection = (state.get("replan_request") or {}).get("source_collection") or {}
    return not source_collection_productive(source_collection)


def decide_replan_route_reason(
    *,
    attempts: int,
    max_attempts_value: int,
    additional_evidence_needed: bool,
    previous_unproductive: bool,
    has_source_path: bool,
) -> str:
    """replan 조건을 표준 reason 문자열로 결정한다."""

    if max_attempts_value <= 0:
        return "replan_disabled"
    if attempts >= max_attempts_value:
        return "max_replan_attempts_reached"
    if not additional_evidence_needed:
        return "no_additional_evidence_needed"
    if previous_unproductive:
        return "previous_replan_unproductive"
    if not has_source_path:
        return "no_replan_source_path"
    return "route_to_replan"


def should_continue_after_replan(state: dict[str, Any]) -> str:
    """replan 후 retrieval로 돌아갈지 Human Review로 갈지 결정한다."""

    request = state.get("replan_request") or {}
    route = request.get("route_after_replan")
    if route in {"retrieve_context", "human_review"}:
        return str(route)
    return "retrieve_context"


def stop_reason_before_source_collection(current_attempts: int, max_attempts_value: int) -> str | None:
    """source 수집 전에 멈춰야 하는 경우 stop reason을 반환한다."""

    if max_attempts_value <= 0:
        return "replan_disabled"
    if current_attempts >= max_attempts_value:
        return "max_replan_attempts_reached"
    return None


def stop_reason_after_source_collection(attempts: int, max_attempts_value: int, productive: bool) -> str | None:
    """source 수집 후 trace에 남길 stop reason을 계산한다."""

    if attempts >= max_attempts_value:
        return "max_replan_attempts_reached_after_current_attempt"
    if not productive:
        return "replan_unproductive_after_current_attempt"
    return None


def route_after_source_collection(productive: bool) -> str:
    """새 근거가 생겼으면 retrieval로, 없으면 Human Review로 route한다."""

    return "retrieve_context" if productive else "human_review"


def build_stopped_replan_request(current_attempts: int, max_attempts_value: int, reason: str) -> dict[str, Any]:
    """source 수집 전 중단된 replan_request payload를 만든다."""

    return {
        "attempt": current_attempts,
        "max_attempts": max_attempts_value,
        "mode": REPLAN_MODE_STOPPED,
        "reason": reason,
        "items": [],
        "source_collection": {},
        "route_after_replan": "human_review",
    }


def build_replan_request(
    *,
    attempts: int,
    max_attempts_value: int,
    replan_items: list[dict[str, Any]],
    source_collection: dict[str, Any],
) -> dict[str, Any]:
    """source 수집 결과를 workflow_state에 저장할 replan_request로 조립한다."""

    productive = source_collection_productive(source_collection)
    return {
        "attempt": attempts,
        "max_attempts": max_attempts_value,
        "mode": REPLAN_MODE_SOURCE_DISCOVERY,
        "reason": "Evaluation & Critic Agent가 일부 후보의 근거 coverage 또는 confidence 부족을 감지했다.",
        "items": replan_items,
        "source_collection": source_collection,
        "route_after_replan": route_after_source_collection(productive),
        "stop_reason": stop_reason_after_source_collection(attempts, max_attempts_value, productive),
        "note": "동일 공식 도메인의 sitemap/link 기반 URL을 자동 수집한다. EXTERNAL_WEB_DISCOVERY_ENABLED=true이면 Brave/SerpAPI 기반 public web search 결과도 보조 출처로 수집한다. 내부 문서 업로드나 인터뷰 메모는 Human Review/API 입력이 필요하다.",
    }
