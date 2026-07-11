"""ESG/컴플라이언스 관련 평가 helper의 기본 동작을 검증한다.
"""

from app.tools.risk_checker import check_process_risk, check_risks_for_processes
from app.tools.score_calculator import rank_agent_candidates


def test_unified_esg_assessment_detects_environmental_social_governance_pillars():
    result = check_process_risk(
        {
            "id": 1,
            "name": "ESG 운영 Agent",
            "problem": "전력 사용량과 탄소 배출을 줄이면서 상담 자동화로 인력 절감 효과도 검토한다.",
            "current_workflow": "법무 승인과 감사 로그 없이 수동으로 보고서를 작성한다.",
            "candidate_agent_name": "ESG Operations Agent",
            "risk_score": 3,
            "data_accessibility": 4,
        }
    )

    pillars = {item["pillar"] for item in result["esg_assessment"]["pillars"]}
    assert pillars == {"environmental", "governance", "social"}
    assert result["esg_assessment"]["review_required"] is True
    assert result["esg_assessment"]["impact_level"] == "review_required"
    assert "esg_assessment_present" in result["flags"]
    assert "esg_review_required" in result["flags"]


def test_environmental_only_esg_signal_is_tracked_without_review_routing():
    result = check_process_risk(
        {
            "id": 2,
            "name": "전력 사용량 리포트 Agent",
            "problem": "전력 사용량과 탄소 배출 산정 근거를 자동 정리한다.",
            "current_workflow": "담당자가 수동으로 데이터를 모은다.",
            "candidate_agent_name": "Energy Reporting Agent",
            "risk_score": 2,
            "data_accessibility": 4,
        }
    )

    pillars = {item["pillar"] for item in result["esg_assessment"]["pillars"]}
    assert pillars == {"environmental"}
    assert result["esg_assessment"]["impact_level"] == "opportunity"
    assert result["esg_assessment"]["review_required"] is False
    assert "esg_assessment_present" in result["flags"]
    assert "esg_review_required" not in result["flags"]


def test_unified_esg_summary_counts_assessment_and_review_separately():
    result = check_risks_for_processes(
        [
            {
                "id": 1,
                "name": "고객 응대 자동화",
                "problem": "상담 자동화로 인력 절감을 기대한다.",
                "risk_score": 3,
                "data_accessibility": 4,
            },
            {
                "id": 2,
                "name": "전력 사용량 리포트 Agent",
                "problem": "전력과 탄소 배출 데이터를 자동 정리한다.",
                "risk_score": 2,
                "data_accessibility": 4,
            },
        ]
    )

    assert result["summary"]["esg_assessment_count"] == 2
    assert result["summary"]["esg_review_required_count"] == 1


def test_unified_esg_review_routes_priority_candidate_to_human_review():
    risk_governance = {
        "items": [
            {
                "process_id": 1,
                "flags": ["esg_assessment_present", "esg_review_required"],
                "esg_assessment": {
                    "impact_level": "review_required",
                    "review_required": True,
                    "pillars": [{"pillar": "social", "categories": ["workforce_impact"], "matched_keywords": ["인력 절감"]}],
                    "required_controls": ["재교육 계획 확인"],
                    "summary": "Agent 도입이 ESG 관점에서 이해관계자 영향 검토를 필요로 한다.",
                },
            }
        ]
    }
    result = rank_agent_candidates(
        processes=[
            {
                "id": 1,
                "name": "상담 자동화",
                "candidate_agent_name": "Customer Service Automation Agent",
                "expected_effect": 5,
                "data_accessibility": 4,
                "repeatability": 5,
                "tech_feasibility": 4,
                "user_acceptance": 3,
                "risk_score": 3,
                "implementation_cost_score": 2,
            }
        ],
        roi_cost={"items": [{"process_id": 1, "saving_rate": 35, "monthly_saving": 1000}]},
        risk_governance=risk_governance,
    )

    item = result["items"][0]
    assert item["status"] == "human_review_required"
    assert result["summary"]["esg_review_required_count"] == 1
    assert "ESG 통합 판단" in item["reason"]
    assert item["esg_assessment"]["review_required"] is True
