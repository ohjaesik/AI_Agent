"""replan 정책 모듈의 route, attempt, request payload 생성을 검증한다."""

from app.graph.replan_policy import (
    build_replan_request,
    decide_replan_route_reason,
    route_after_source_collection,
    source_collection_productive,
    stop_reason_after_source_collection,
)


def test_decide_replan_route_reason_uses_ordered_guards() -> None:
    assert decide_replan_route_reason(
        attempts=0,
        max_attempts_value=0,
        additional_evidence_needed=True,
        previous_unproductive=False,
        has_source_path=True,
    ) == "replan_disabled"
    assert decide_replan_route_reason(
        attempts=1,
        max_attempts_value=1,
        additional_evidence_needed=True,
        previous_unproductive=False,
        has_source_path=True,
    ) == "max_replan_attempts_reached"
    assert decide_replan_route_reason(
        attempts=0,
        max_attempts_value=2,
        additional_evidence_needed=True,
        previous_unproductive=False,
        has_source_path=True,
    ) == "route_to_replan"


def test_source_collection_productivity_controls_route_after_replan() -> None:
    productive = {"same_domain_discovered": [{"url": "https://example.com/a"}], "public_web_search": {"results": []}}
    empty = {"same_domain_discovered": [], "public_web_search": {"results": []}, "loaded": [], "indexed_chunks": 0}

    assert source_collection_productive(productive) is True
    assert source_collection_productive(empty) is False
    assert route_after_source_collection(True) == "retrieve_context"
    assert route_after_source_collection(False) == "human_review"


def test_build_replan_request_records_route_and_stop_reason() -> None:
    request = build_replan_request(
        attempts=1,
        max_attempts_value=1,
        replan_items=[{"process_id": 10}],
        source_collection={"indexed_chunks": 12, "same_domain_discovered": [], "public_web_search": {"results": []}},
    )

    assert request["route_after_replan"] == "retrieve_context"
    assert request["stop_reason"] == "max_replan_attempts_reached_after_current_attempt"
    assert stop_reason_after_source_collection(1, 3, False) == "replan_unproductive_after_current_attempt"
