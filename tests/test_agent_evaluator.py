from app.agents.evaluator import evaluate_agent_outputs


def test_agent_evaluator_downgrades_low_evidence_recommended_candidate():
    state = {
        "priority_ranking": {
            "items": [
                {
                    "process_id": 1,
                    "candidate_agent_name": "Low Evidence Agent",
                    "status": "recommended",
                    "final_score": 4.0,
                    "saving_rate": 60.0,
                    "risk_score": 3,
                    "data_accessibility": 3,
                    "discovery_metadata": {"evidence_labels": []},
                    "score_rationale": {},
                    "compliance": {},
                }
            ],
            "summary": {"total_candidates": 1},
        },
        "retrieved_contexts": {"1": []},
        "evidence_items": [],
    }

    result = evaluate_agent_outputs(state)
    updated = result["updated_priority_ranking"]["items"][0]

    assert result["summary"]["evaluated_candidates"] == 1
    assert result["summary"]["low_confidence_count"] == 1
    assert updated["status"] == "evidence_insufficient"
    assert updated["agent_evaluation"]["requires_additional_evidence"] is True


def test_evaluator_returns_tool_permissions_not_agent_registry():
    state = {
        "priority_ranking": {"items": [], "summary": {"total_candidates": 0}},
        "retrieved_contexts": {},
        "evidence_items": [],
    }

    result = evaluate_agent_outputs(state)

    assert "agent_registry" not in result
    assert "agent_tool_permissions" in result
    assert {row["agent_id"] for row in result["agent_tool_permissions"]} == {
        "company_onboarding_agent",
        "context_evidence_agent",
        "process_diagnosis_agent",
        "business_case_agent",
        "governance_compliance_agent",
        "evaluation_critic_agent",
        "delivery_orchestration_agent",
    }


def test_zero_evidence_coverage_is_evidence_insufficient_even_with_rationale():
    state = {
        "priority_ranking": {
            "items": [
                {
                    "process_id": 3,
                    "candidate_agent_name": "No Tool Output Agent",
                    "status": "recommended",
                    "final_score": 4.0,
                    "saving_rate": 60.0,
                    "risk_score": 1,
                    "data_accessibility": 4,
                    "discovery_metadata": {"evidence_labels": []},
                    "score_rationale": {
                        "expected_effect": "ok",
                        "repeatability": "ok",
                        "document_dependency": "ok",
                        "data_accessibility": "ok",
                        "tech_feasibility": "ok",
                        "risk_score": "ok",
                    },
                    "compliance": {},
                }
            ],
            "summary": {"total_candidates": 1},
        },
        "retrieved_contexts": {"3": []},
        "evidence_items": [],
    }

    result = evaluate_agent_outputs(state)
    updated = result["updated_priority_ranking"]["items"][0]

    assert updated["status"] == "evidence_insufficient"
    assert updated["agent_evaluation"]["zero_evidence_coverage"] is True
    assert updated["agent_evaluation"]["requires_additional_evidence"] is True


def test_agent_evaluator_respects_compliance_human_review_requirement():
    state = {
        "priority_ranking": {
            "items": [
                {
                    "process_id": 2,
                    "candidate_agent_name": "Sensitive Agent",
                    "status": "recommended",
                    "final_score": 4.2,
                    "saving_rate": 70.0,
                    "risk_score": 2,
                    "data_accessibility": 5,
                    "discovery_metadata": {"evidence_labels": ["[공식URL-1]", "[DART-기업개황]"]},
                    "score_rationale": {
                        "expected_effect": "ok",
                        "repeatability": "ok",
                        "document_dependency": "ok",
                        "data_accessibility": "ok",
                        "tech_feasibility": "ok",
                        "risk_score": "ok",
                    },
                }
            ],
            "summary": {"total_candidates": 1},
        },
        "retrieved_contexts": {"2": [{"content": "a"}, {"content": "b"}, {"content": "c"}]},
        "evidence_items": [{"process_id": 2}, {"process_id": 2}],
        "compliance_assessment": {
            "items": [
                {
                    "process_id": 2,
                    "compliance_level": "sensitive_review",
                    "human_review_required": True,
                    "blocked": False,
                }
            ]
        },
    }

    result = evaluate_agent_outputs(state)
    updated = result["updated_priority_ranking"]["items"][0]

    assert updated["status"] == "human_review_required"
    assert updated["compliance"]["compliance_level"] == "sensitive_review"
    assert updated["agent_evaluation"]["requires_human_review"] is True
