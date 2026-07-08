import json

from app.evaluation.holdout_candidate_exporter import export_unlabeled_holdout_candidates


def test_export_unlabeled_holdout_candidates(tmp_path):
    state = {
        "project_id": 1,
        "company_id": 2,
        "priority_ranking": {
            "items": [
                {
                    "process_id": 10,
                    "candidate_agent_name": "Borderline Agent",
                    "status": "human_review_required",
                    "final_score": 3.8,
                    "saving_rate": 45.0,
                    "risk_score": 3,
                    "data_accessibility": 3,
                    "discovery_metadata": {"evidence_labels": ["[공식URL-1]"]},
                    "score_rationale": {"expected_effect": "ok", "repeatability": "ok"},
                    "agent_evaluation": {
                        "confidence_score": 0.64,
                        "evidence_coverage": 0.42,
                        "data_confidence": 0.50,
                        "rationale_coverage": 0.33,
                        "risk_uncertainty": 0.25,
                        "replan_evidence_lift": 0.0,
                    },
                    "compliance": {"compliance_level": "standard", "blocked": False},
                }
            ]
        },
        "retrieved_contexts": {"10": [{"content": "a"}]},
        "evidence_items": [{"process_id": 10}],
    }

    csv_path = tmp_path / "candidates.csv"
    jsonl_path = tmp_path / "candidates.jsonl"

    rows = export_unlabeled_holdout_candidates(
        state=state,
        csv_path=csv_path,
        jsonl_path=jsonl_path,
        case_id_prefix="test-holdout",
        borderline_only=True,
    )

    assert len(rows) == 1
    assert rows[0]["case_id"] == "test-holdout-001"
    assert rows[0]["expected_status"] == ""
    assert rows[0]["expected_requires_human_review"] == ""
    assert "confidence_band" in rows[0]["borderline_reason"]
    assert csv_path.exists()
    assert jsonl_path.exists()

    payload = json.loads(jsonl_path.read_text(encoding="utf-8").strip())
    assert payload["case_id"] == "test-holdout-001"
    assert payload["expected_status"] == ""
