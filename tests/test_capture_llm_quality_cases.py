from __future__ import annotations

from app.evaluation.capture_llm_quality_cases import build_cases_from_state


def test_build_cases_from_state_extracts_llm_outputs() -> None:
    state = {
        "official_sources": [{"label": "[SRC-1]"}],
        "process_specs": [
            {
                "department": "운영/생산",
                "name": "문서 검색 업무",
                "target_user": "담당자",
                "problem": "근거 검색 필요 [SRC-1]",
                "current_workflow": "수동 검색 [SRC-1]",
                "candidate_agent_name": "문서 검색 Agent",
                "expected_effect": 4,
                "repeatability": 4,
                "document_dependency": 4,
                "decision_complexity": 3,
                "data_accessibility": 3,
                "tech_feasibility": 4,
                "user_acceptance": 4,
                "risk_score": 3,
                "implementation_cost_score": 3,
                "evidence_labels": ["[SRC-1]"],
            }
        ],
        "priority_ranking": {
            "items": [
                {
                    "process_id": 1,
                    "candidate_agent_name": "문서 검색 Agent",
                    "status": "recommended",
                }
            ]
        },
        "agent_evaluation": {
            "items": [
                {
                    "process_id": 1,
                    "confidence_score": 0.82,
                    "requires_human_review": False,
                    "requires_additional_evidence": False,
                    "issues": [],
                    "llm_critic": {
                        "critic_verdict": "pass",
                        "critic_confidence_adjustment": 0.0,
                        "critic_reason": "정량 기준을 충족했다.",
                        "missing_evidence": [],
                        "review_questions": [],
                        "critic_mode": "llm_critic",
                    },
                }
            ]
        },
        "evidence_items": [{"citation_label": "[DOC-1]"}],
        "report_data": {
            "sections": [
                {
                    "heading": "1. 분석 개요",
                    "blocks": [{"type": "paragraph", "text": "근거 문장 [DOC-1]"}],
                }
            ],
            "generation": {"mode": "vllm_report_writer"},
        },
    }

    cases = build_cases_from_state(
        state,
        case_prefix="sample",
        expected_min_processes=1,
        expected_max_processes=2,
        freeze_current_verdict=True,
    )

    assert [case["target"] for case in cases] == [
        "company_process_discovery",
        "llm_critic",
        "report_writer",
    ]
    assert cases[0]["allowed_labels"] == ["[SRC-1]", "[DOC-1]"]
    assert cases[1]["expected_verdict"] == "pass"
    assert cases[2]["evidence_items"] == [{"citation_label": "[DOC-1]"}]
