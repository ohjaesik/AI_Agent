from app.evaluation.agent_quality_eval import DEFAULT_GOLD_PATH, evaluate_cases, load_jsonl


def test_agent_quality_gold_set_has_at_least_20_cases():
    cases = load_jsonl(DEFAULT_GOLD_PATH)
    assert len(cases) >= 20


def test_agent_quality_eval_returns_metrics():
    cases = load_jsonl(DEFAULT_GOLD_PATH)
    metrics = evaluate_cases(cases)

    assert metrics["total_cases"] == len(cases)
    assert 0.0 <= metrics["status_accuracy"] <= 1.0
    assert 0.0 <= metrics["review_gate_accuracy"] <= 1.0
    assert len(metrics["results"]) == len(cases)
