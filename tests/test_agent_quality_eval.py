"""오프라인 Agent 품질 평가 helper가 기대 metric을 계산하는지 검증한다.
"""

from app.evaluation.agent_quality_eval import (
    BLIND_HOLDOUT_GOLD_PATH,
    DEFAULT_GOLD_PATH,
    evaluate_cases,
    load_dataset_cases,
    load_gold_cases,
    load_holdout_cases,
    quality_gate,
)


def test_agent_quality_regression_set_has_at_least_100_cases():
    cases = load_gold_cases(DEFAULT_GOLD_PATH)
    assert len(cases) >= 100


def test_agent_quality_holdout_set_has_at_least_30_cases():
    cases = load_holdout_cases(BLIND_HOLDOUT_GOLD_PATH)
    assert len(cases) >= 30


def test_load_dataset_cases_distinguishes_regression_and_holdout():
    regression_cases, regression_name, _ = load_dataset_cases("regression")
    holdout_cases, holdout_name, _ = load_dataset_cases("holdout")

    assert regression_name == "regression"
    assert holdout_name == "holdout"
    assert len(regression_cases) >= 100
    assert len(holdout_cases) >= 30
    assert regression_cases[0]["case_id"] != holdout_cases[0]["case_id"]


def test_agent_quality_eval_returns_detailed_metrics():
    cases = load_gold_cases(DEFAULT_GOLD_PATH)
    metrics = evaluate_cases(cases, evaluation_set="regression", case_source=str(DEFAULT_GOLD_PATH))

    assert metrics["evaluation_set"] == "regression"
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
