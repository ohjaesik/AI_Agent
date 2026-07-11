"""Evaluation/Critic 공통 정책 모듈의 경계값과 route 분기를 검증한다."""

from app.agents.evaluation_policy import (
    build_evaluation_route,
    deterministic_critic_verdict,
    split_evidence_decision_ids,
)


def test_evaluation_policy_routes_moderate_gap_to_auto_replan() -> None:
    route = build_evaluation_route(
        candidate_status="recommended",
        compliance={"compliance_level": "standard", "human_review_required": False},
        risk_uncertainty=0.0,
        confidence_score=0.71,
        human_review_threshold=0.65,
        issues=[],
        requires_additional_evidence=True,
        zero_evidence_coverage=False,
        very_weak_evidence_coverage=False,
    )

    assert route["requires_human_review"] is False
    assert route["autonomy_route"] == "auto_replan"


def test_evaluation_policy_keeps_compliance_review_as_human_review() -> None:
    route = build_evaluation_route(
        candidate_status="recommended",
        compliance={"compliance_level": "sensitive_review", "human_review_required": True},
        risk_uncertainty=0.25,
        confidence_score=0.78,
        human_review_threshold=0.65,
        issues=[],
        requires_additional_evidence=False,
        zero_evidence_coverage=False,
        very_weak_evidence_coverage=False,
    )

    assert route["requires_human_review"] is True
    assert route["autonomy_route"] == "human_review"


def test_deterministic_critic_verdict_distinguishes_replan_and_insufficient() -> None:
    candidate = {"status": "recommended", "compliance": {"compliance_level": "standard", "blocked": False}}

    moderate_gap = {
        "confidence_score": 0.71,
        "evidence_coverage": 0.38,
        "compliance_alignment": 1.0,
        "requires_additional_evidence": True,
        "requires_human_review": False,
        "zero_evidence_coverage": False,
        "very_weak_evidence_coverage": False,
        "issues": [],
    }
    severe_gap = {**moderate_gap, "evidence_coverage": 0.0, "zero_evidence_coverage": True}

    assert deterministic_critic_verdict(candidate, moderate_gap) == "needs_replan"
    assert deterministic_critic_verdict(candidate, severe_gap) == "insufficient_evidence"


def test_split_evidence_decision_ids_separates_three_routes() -> None:
    insufficient_ids, review_ids, replan_ids = split_evidence_decision_ids(
        {
            "items": [
                {
                    "process_id": 1,
                    "requires_additional_evidence": True,
                    "evidence_coverage": 0.0,
                    "confidence_score": 0.3,
                    "zero_evidence_coverage": True,
                },
                {
                    "process_id": 2,
                    "requires_human_review": True,
                    "requires_additional_evidence": False,
                    "evidence_coverage": 0.7,
                    "confidence_score": 0.8,
                },
                {
                    "process_id": 3,
                    "requires_additional_evidence": True,
                    "requires_human_review": False,
                    "evidence_coverage": 0.38,
                    "confidence_score": 0.71,
                    "llm_critic": {"critic_verdict": "needs_replan"},
                },
            ]
        }
    )

    assert insufficient_ids == {1}
    assert review_ids == {2}
    assert replan_ids == {3}
