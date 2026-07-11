"""모델 선택 trace의 top-level 비용 요약 집계를 검증한다."""

from __future__ import annotations

from app.agents.cost_summary import build_total_cost_summary


def test_total_cost_summary_rolls_up_unique_model_decisions() -> None:
    decisions = [
        {
            "decision_id": "supervisor-1",
            "agent_id": "supervisor_agent",
            "call_kind": "supervisor_delegation",
            "provider": "openai",
            "model": "gpt-5.5-sol",
            "estimated_cost_usd": 0.012,
            "cost_calculation": {
                "estimated_input_tokens": 1000,
                "estimated_output_tokens": 500,
                "total_cost_usd": 0.012,
            },
        },
        {
            "decision_id": "supervisor-1",
            "agent_id": "supervisor_agent",
            "call_kind": "supervisor_delegation",
            "provider": "openai",
            "model": "gpt-5.5-sol",
            "estimated_cost_usd": 0.012,
            "cost_calculation": {
                "estimated_input_tokens": 1000,
                "estimated_output_tokens": 500,
                "total_cost_usd": 0.012,
            },
        },
        {
            "agent_id": "context_evidence_agent",
            "call_kind": "agent_command",
            "provider": "vllm",
            "model": "gemma-4-e4b-it",
            "cost_calculation": {
                "estimated_input_tokens": 2000,
                "estimated_output_tokens": 250,
                "total_cost_usd": 0.003,
            },
        },
    ]

    summary = build_total_cost_summary(decisions)

    assert summary["estimated_total_cost_usd"] == 0.015
    assert summary["decision_count"] == 2
    assert summary["priced_decision_count"] == 2
    assert summary["by_provider"]["openai"]["estimated_cost_usd"] == 0.012
    assert summary["by_provider"]["vllm"]["estimated_cost_usd"] == 0.003
    assert summary["by_model"]["openai:gpt-5.5-sol"]["decision_count"] == 1
    assert summary["by_call_kind"]["agent_command"]["estimated_input_tokens"] == 2000
