from app.evaluation.agent_quality_eval import DEFAULT_GOLD_PATH, evaluate_cases, load_gold_cases, quality_gate


def test_agent_quality_gold_set_has_at_least_100_cases():
    cases = load_gold_cases(DEFAULT_GOLD_PATH)
    assert len(cases) >= 100


def test_agent_quality_eval_returns_detailed_metrics():
    cases = load_gold_cases(DEFAULT_GOLD_PATH)
    metrics = evaluate_cases(cases)

    assert metrics["total_cases"] == len(cases)
    assert 0.0 <= metrics["status_accuracy"] <= 1.0
    assert 0.0 <= metrics["review_gate_accuracy"] <= 1.0
    assert 0.0 <= metrics["status_macro_f1"] <= 1.0
    assert 0.0 <= metrics["status_weighted_f1"] <= 1.0
    assert 0.0 <= metrics["review_gate_f1"] <= 1.0
    assert len(metrics["results"]) == len(cases)
    assert isinstance(metrics["confusion_matrix"], dict)
    assert isinstance(metrics["status_report"], dict)
    assert isinstance(metrics["review_gate_report"], dict)
    assert isinstance(metrics["misclassified"], list)


def test_agent_quality_gate_returns_boolean():
    metrics = {
        "status_accuracy": 0.9,
        "review_gate_accuracy": 0.95,
        "status_macro_f1": 0.85,
        "review_gate_f1": 0.95,
    }
    gate = quality_gate(
        metrics,
        min_status_accuracy=0.8,
        min_review_accuracy=0.9,
        min_status_macro_f1=0.75,
        min_review_f1=0.9,
    )
    assert gate["passed"] is True
    assert all(gate["checks"].values())
