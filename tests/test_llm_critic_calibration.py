"""LLM critic 결과가 ranking status를 보수적으로 보정하는지 검증한다.
"""

from app.agents.llm_critic import calibrate_critic_verdict, deterministic_verdict


def test_deterministic_verdict_pass_for_standard_strong_candidate():
    candidate = {"status": "recommended", "compliance": {"compliance_level": "standard", "blocked": False}}
    evaluation = {
        "confidence_score": 0.76,
        "compliance_alignment": 1.0,
        "requires_additional_evidence": False,
        "requires_human_review": False,
        "issues": [],
    }

    assert deterministic_verdict(candidate, evaluation) == "pass"


def test_calibrate_critic_overrides_overconservative_review():
    candidate = {"status": "recommended", "compliance": {"compliance_level": "standard", "blocked": False}}
    evaluation = {
        "confidence_score": 0.76,
        "compliance_alignment": 1.0,
        "requires_additional_evidence": False,
        "requires_human_review": False,
        "issues": [],
    }
    critic = {
        "critic_verdict": "needs_review",
        "critic_confidence_adjustment": -0.05,
        "critic_reason": "too conservative",
        "missing_evidence": ["extra"],
        "review_questions": ["q"],
        "critic_mode": "llm_critic",
    }

    calibrated = calibrate_critic_verdict(candidate, evaluation, critic)

    assert calibrated["critic_verdict"] == "pass"
    assert calibrated["critic_calibrated"] is True
    assert calibrated["missing_evidence"] == []
