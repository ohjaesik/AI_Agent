"""LLM 출력 품질 평가 metric과 JSON 검사 로직을 검증한다.
"""

from __future__ import annotations

from app.evaluation.llm_quality_eval import (
    DEFAULT_CASE_PATH,
    evaluate_case,
    evaluate_cases,
    load_jsonl,
    quality_gate,
)


def test_default_llm_quality_cases_pass() -> None:
    cases = load_jsonl(DEFAULT_CASE_PATH)

    metrics = evaluate_cases(cases, case_source=str(DEFAULT_CASE_PATH))

    assert metrics["total_cases"] == 3
    assert metrics["pass_rate"] == 1.0
    assert metrics["json_parse_success_rate"] == 1.0
    assert metrics["schema_valid_rate"] == 1.0
    assert metrics["fallback_free_rate"] == 1.0
    assert not metrics["failed_cases"]


def test_llm_critic_quality_case_blocks_unsafe_pass() -> None:
    result = evaluate_case(
        {
            "case_id": "critic_unsafe_pass",
            "target": "llm_critic",
            "expected_not_pass": True,
            "payload": {
                "critic_verdict": "pass",
                "critic_confidence_adjustment": 0.0,
                "critic_reason": "통과로 판단했다.",
                "missing_evidence": [],
                "review_questions": [],
                "critic_mode": "llm_critic",
            },
        }
    )

    assert result["passed"] is False
    assert result["checks"]["unsafe_pass"] is True


def test_company_process_discovery_rejects_unknown_evidence_label() -> None:
    result = evaluate_case(
        {
            "case_id": "discovery_bad_label",
            "target": "company_process_discovery",
            "allowed_labels": ["[SRC-1]"],
            "expected_min_processes": 1,
            "expected_max_processes": 1,
            "payload": {
                "processes": [
                    {
                        "department": "운영/생산",
                        "name": "업무",
                        "target_user": "담당자",
                        "problem": "문제 [SRC-2]",
                        "current_workflow": "현재 흐름 [SRC-2]",
                        "candidate_agent_name": "업무 Agent",
                        "expected_effect": 4,
                        "repeatability": 4,
                        "document_dependency": 4,
                        "decision_complexity": 3,
                        "data_accessibility": 3,
                        "tech_feasibility": 4,
                        "user_acceptance": 4,
                        "risk_score": 3,
                        "implementation_cost_score": 3,
                        "evidence_labels": ["[SRC-2]"],
                    }
                ]
            },
        }
    )

    assert result["passed"] is False
    assert result["checks"]["evidence_label_valid"] is False


def test_quality_gate_uses_llm_specific_thresholds() -> None:
    metrics = {
        "pass_rate": 0.9,
        "json_parse_success_rate": 1.0,
        "schema_valid_rate": 0.9,
        "fallback_free_rate": 0.6,
    }

    gate = quality_gate(
        metrics,
        min_pass_rate=0.9,
        min_json_parse_success_rate=0.95,
        min_schema_valid_rate=0.9,
        min_fallback_free_rate=0.7,
    )

    assert gate["passed"] is False
    assert gate["checks"]["fallback_free_rate"] is False
