from app.evaluation.agent_quality_eval import DEFAULT_GOLD_PATH, evaluate_cases, load_jsonl, quality_gate


def test_agent_quality_gold_set_has_at_least_50_cases():
    cases = load_jsonl(DEFAULT_GOLD_PATH)
    assert len(cases) >= 50


def test_agent_quality_eval_returns_metrics():
    cases = load_jsonl(DEFAULT_GOLD_PATH)
    metrics = evaluate_cases(cases)

    assert metrics["total_cases"] == len(cases)
    assert 0.0 <= metrics["status_accuracy"] <= 1.0
    assert 0.0 <= metrics["review_gate_accuracy"] <= 1.0
    assert len(metrics["results"]) == len(cases)
    assert isinstance(metrics["confusion_matrix"], dict)


def test_agent_quality_gate_returns_boolean():
    metrics = {"status_accuracy": 0.9, "review_gate_accuracy": 0.95}
    gate = quality_gate(metrics, min_status_accuracy=0.8, min_review_accuracy=0.9)
    assert gate["passed"] is True
