from app.agents.evaluator import compute_replan_evidence_lift, evaluate_candidate


def test_compute_replan_evidence_lift_from_public_web_and_chunks():
    state = {
        "replan_request": {
            "source_collection": {
                "public_web_search": {"results": [{"url": "https://a.example"}, {"url": "https://b.example"}, {"url": "https://c.example"}]},
                "same_domain_discovered": [],
                "indexed_chunks": 47,
            }
        }
    }

    lift = compute_replan_evidence_lift(state)

    assert lift > 0.10
    assert lift <= 0.15


def test_replan_evidence_lift_increases_evaluation_scores():
    candidate = {
        "process_id": 1,
        "candidate_agent_name": "Product Advisor Agent",
        "status": "human_review_required",
        "data_accessibility": 4,
        "risk_score": 1,
        "discovery_metadata": {"evidence_labels": ["[공식URL-1]"]},
        "score_rationale": {
            "expected_effect": "high",
            "repeatability": "high",
            "document_dependency": "medium",
            "data_accessibility": "high",
            "tech_feasibility": "high",
            "risk_score": "low",
        },
        "compliance": {"compliance_level": "standard", "human_review_required": False, "blocked": False},
    }

    before = evaluate_candidate(candidate, context_count=3, evidence_count=1, replan_evidence_lift=0.0)
    after = evaluate_candidate(candidate, context_count=3, evidence_count=1, replan_evidence_lift=0.13)

    assert after["confidence_score"] > before["confidence_score"]
    assert after["evidence_coverage"] > before["evidence_coverage"]
    assert after["replan_evidence_lift"] == 0.13
