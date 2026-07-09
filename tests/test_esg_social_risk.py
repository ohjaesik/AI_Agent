from app.tools.risk_checker import check_process_risk, check_risks_for_processes
from app.tools.score_calculator import rank_agent_candidates


def test_workforce_displacement_triggers_social_impact_review():
    result = check_process_risk(
        {
            "id": 1,
            "name": "고객 상담 자동화",
            "problem": "반복 상담 업무를 Agent로 대체하여 인력 절감 효과를 기대한다.",
            "current_workflow": "상담원이 수동으로 문의를 분류한다.",
            "candidate_agent_name": "Customer Service Automation Agent",
            "risk_score": 3,
            "data_accessibility": 4,
        }
    )

    assert "social_impact_review_required" in result["flags"]
    assert "workforce_transition_required" in result["flags"]
    assert result["esg_social_risks"][0]["category"] == "workforce_displacement"
    assert result["esg_social_controls"]


def test_employee_monitoring_triggers_guardrail():
    result = check_process_risk(
        {
            "id": 2,
            "name": "작업자 모니터링 Agent",
            "problem": "작업자 모니터링과 생산성 추적을 자동화한다.",
            "current_workflow": "관리자가 작업 로그를 확인한다.",
            "candidate_agent_name": "Worker Monitoring Agent",
            "risk_score": 3,
            "data_accessibility": 4,
        }
    )

    assert "social_impact_review_required" in result["flags"]
    assert "employee_monitoring_guardrail_required" in result["flags"]
    assert any(risk["category"] == "employee_monitoring" for risk in result["esg_social_risks"])


def test_social_impact_review_count_in_summary():
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
                "name": "문서 검색 Agent",
                "problem": "내부 문서 검색 시간을 줄인다.",
                "risk_score": 2,
                "data_accessibility": 4,
            },
        ]
    )

    assert result["summary"]["social_impact_review_count"] == 1


def test_social_impact_risk_routes_priority_candidate_to_human_review():
    risk_governance = {
        "items": [
            {
                "process_id": 1,
                "flags": ["social_impact_review_required", "workforce_transition_required"],
                "esg_social_risks": [{"category": "workforce_displacement", "matched_keywords": ["인력 절감"]}],
                "esg_social_controls": ["재교육 계획 확인"],
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
    assert result["summary"]["social_impact_review_count"] == 1
    assert "ESG Social" in item["reason"]
    assert item["esg_social_risks"]
