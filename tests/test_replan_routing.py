from app.core.config import get_settings
from app.graph.replan_node import (
    build_replan_items,
    current_replan_attempts,
    replan_route_reason,
    should_continue_after_replan,
    should_replan,
)


def configure_settings(monkeypatch, max_attempts="1", external_discovery="false"):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/test")
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("AGENT_REPLAN_MAX_ATTEMPTS", max_attempts)
    monkeypatch.setenv("EXTERNAL_WEB_DISCOVERY_ENABLED", external_discovery)
    get_settings.cache_clear()


def evidence_gap_state(**overrides):
    state = {
        "company_id": 1,
        "company_profile": {"name": "DemoCo"},
        "used_sources": [{"url": "https://example.com/company"}],
        "documents": [],
        "replan_attempts": 0,
        "agent_evaluation": {
            "summary": {"additional_evidence_required_count": 1},
            "items": [
                {
                    "process_id": 10,
                    "candidate_agent_name": "SOP Search Agent",
                    "requires_additional_evidence": True,
                    "evidence_coverage": 0.2,
                    "confidence_score": 0.4,
                    "issues": ["low evidence coverage"],
                }
            ],
        },
        "priority_ranking": {
            "items": [
                {
                    "process_id": 10,
                    "process_name": "SOP 검색",
                    "candidate_agent_name": "SOP Search Agent",
                    "target_user": "생산팀",
                }
            ]
        },
    }
    state.update(overrides)
    return state


def test_should_replan_routes_when_evidence_gap_and_source_path_exists(monkeypatch):
    configure_settings(monkeypatch, max_attempts="1")

    state = evidence_gap_state()

    assert replan_route_reason(state) == "route_to_replan"
    assert should_replan(state) == "agent_replan"


def test_should_replan_routes_to_human_when_attempt_limit_reached(monkeypatch):
    configure_settings(monkeypatch, max_attempts="1")

    state = evidence_gap_state(replan_attempts=1)

    assert replan_route_reason(state) == "max_replan_attempts_reached"
    assert should_replan(state) == "human_review"


def test_should_replan_can_be_disabled(monkeypatch):
    configure_settings(monkeypatch, max_attempts="0")

    state = evidence_gap_state()

    assert replan_route_reason(state) == "replan_disabled"
    assert should_replan(state) == "human_review"


def test_should_replan_routes_to_human_without_source_path(monkeypatch):
    configure_settings(monkeypatch, max_attempts="1", external_discovery="false")

    state = evidence_gap_state(used_sources=[], documents=[])

    assert replan_route_reason(state) == "no_replan_source_path"
    assert should_replan(state) == "human_review"


def test_should_replan_allows_external_discovery_as_source_path(monkeypatch):
    configure_settings(monkeypatch, max_attempts="1", external_discovery="true")

    state = evidence_gap_state(used_sources=[], documents=[])

    assert replan_route_reason(state) == "route_to_replan"
    assert should_replan(state) == "agent_replan"


def test_should_replan_routes_to_human_after_unproductive_replan(monkeypatch):
    configure_settings(monkeypatch, max_attempts="3")

    state = evidence_gap_state(
        replan_attempts=1,
        replan_request={
            "source_collection": {
                "same_domain_discovered": [],
                "public_web_search": {"results": []},
                "loaded": [],
                "indexed_chunks": 0,
            }
        },
    )

    assert replan_route_reason(state) == "previous_replan_unproductive"
    assert should_replan(state) == "human_review"


def test_current_replan_attempts_uses_request_attempt_fallback():
    state = evidence_gap_state(
        replan_attempts=0,
        replan_request={"attempt": 2},
    )

    assert current_replan_attempts(state) == 2


def test_should_continue_after_replan_can_route_directly_to_human_review():
    state = evidence_gap_state(
        replan_request={
            "attempt": 3,
            "max_attempts": 3,
            "route_after_replan": "human_review",
            "stop_reason": "max_replan_attempts_reached_after_current_attempt",
        }
    )

    assert should_continue_after_replan(state) == "human_review"


def test_should_continue_after_replan_defaults_to_retrieve_context():
    state = evidence_gap_state(replan_request={"attempt": 1})

    assert should_continue_after_replan(state) == "retrieve_context"


def test_build_replan_items_caps_items():
    evaluations = [
        {
            "process_id": index,
            "candidate_agent_name": f"Agent {index}",
            "requires_additional_evidence": True,
            "evidence_coverage": 0.2,
            "confidence_score": 0.4,
        }
        for index in range(10)
    ]
    state = evidence_gap_state(
        agent_evaluation={
            "summary": {"additional_evidence_required_count": 10},
            "items": evaluations,
        },
        priority_ranking={"items": []},
    )

    assert len(build_replan_items(state)) == 5
