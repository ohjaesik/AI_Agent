from __future__ import annotations

from types import SimpleNamespace

import app.graph.replan_node as replan_node


def patch_replan_settings(monkeypatch, *, attempts: int = 0, items: int = 3, sources: int = 1) -> None:
    monkeypatch.setattr(
        replan_node,
        "get_settings",
        lambda: SimpleNamespace(
            agent_replan_max_attempts=attempts,
            agent_replan_max_items=items,
            agent_replan_max_new_sources=sources,
            external_web_discovery_enabled=False,
            external_web_max_results=3,
        ),
    )


def evidence_gap_state() -> dict:
    return {
        "agent_evaluation": {
            "summary": {"additional_evidence_required_count": 1},
            "items": [
                {
                    "process_id": 1,
                    "candidate_agent_name": "문서 검색 Agent",
                    "requires_additional_evidence": True,
                    "evidence_coverage": 0.2,
                    "confidence_score": 0.4,
                    "issues": ["근거 부족"],
                }
            ],
        },
        "priority_ranking": {
            "items": [
                {
                    "process_id": 1,
                    "process_name": "문서 검색 업무",
                    "candidate_agent_name": "문서 검색 Agent",
                    "target_user": "담당자",
                }
            ]
        },
        "documents": [{"source_url": "https://example.com/source"}],
    }


def test_replan_disabled_by_default_routes_to_human_review(monkeypatch) -> None:
    patch_replan_settings(monkeypatch, attempts=0)

    assert replan_node.replan_route_reason(evidence_gap_state()) == "replan_disabled"
    assert replan_node.should_replan(evidence_gap_state()) == "human_review"


def test_replan_routes_when_explicitly_enabled(monkeypatch) -> None:
    patch_replan_settings(monkeypatch, attempts=1)

    assert replan_node.replan_route_reason(evidence_gap_state()) == "route_to_replan"
    assert replan_node.should_replan(evidence_gap_state()) == "agent_replan"


def test_replan_item_count_is_capped(monkeypatch) -> None:
    patch_replan_settings(monkeypatch, attempts=1, items=1)
    state = evidence_gap_state()
    state["agent_evaluation"]["items"].append(
        {
            "process_id": 2,
            "candidate_agent_name": "추가 Agent",
            "requires_additional_evidence": True,
            "evidence_coverage": 0.2,
            "confidence_score": 0.4,
            "issues": ["근거 부족"],
        }
    )
    state["priority_ranking"]["items"].append(
        {
            "process_id": 2,
            "process_name": "추가 업무",
            "candidate_agent_name": "추가 Agent",
            "target_user": "담당자",
        }
    )

    assert len(replan_node.build_replan_items(state)) == 1


def test_continue_after_replan_stops_when_attempt_limit_reached(monkeypatch) -> None:
    patch_replan_settings(monkeypatch, attempts=1)
    state = {
        "replan_attempts": 1,
        "replan_request": {
            "attempt": 1,
            "route_after_replan": "retrieve_context",
            "source_collection": {"indexed_chunks": 10},
        },
    }

    assert replan_node.should_continue_after_replan(state) == "human_review"
