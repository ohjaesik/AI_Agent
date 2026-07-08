import csv
import json

from app.evaluation.finalize_labeled_holdout import load_labels_from_csv, merge_labels, write_jsonl


def test_finalize_labeled_holdout_merges_csv_labels(tmp_path):
    unlabeled = [
        {
            "case_id": "graph-holdout-v2-001",
            "process_id": 1,
            "candidate_agent_name": "Borderline Agent",
            "initial_status": "recommended",
            "evidence_labels": ["[공식URL-1]"],
            "context_count": 1,
            "evidence_count": 1,
            "data_accessibility": 2,
            "risk_score": 2,
            "score_rationale": {"expected_effect": "ok"},
            "expected_status": "",
            "expected_requires_human_review": "",
            "labeling_note": "fill me",
        }
    ]
    csv_path = tmp_path / "labeled.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["case_id", "expected_status", "expected_requires_human_review"])
        writer.writeheader()
        writer.writerow(
            {
                "case_id": "graph-holdout-v2-001",
                "expected_status": "human_review_required",
                "expected_requires_human_review": "true",
            }
        )

    labels = load_labels_from_csv(csv_path)
    merged = merge_labels(unlabeled, labels)

    assert merged[0]["expected_status"] == "human_review_required"
    assert merged[0]["expected_requires_human_review"] is True
    assert "labeling_note" not in merged[0]

    output = tmp_path / "gold.jsonl"
    write_jsonl(output, merged)
    payload = json.loads(output.read_text(encoding="utf-8").strip())
    assert payload["case_id"] == "graph-holdout-v2-001"
