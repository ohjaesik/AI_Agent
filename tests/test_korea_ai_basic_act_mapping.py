from app.compliance.assessment import assess_ai_compliance, classify_process
from app.compliance.regulatory_policy import get_korea_ai_basic_act_reference, get_regulatory_controls


def test_standard_process_includes_korea_ai_basic_act_requirements():
    result = classify_process(
        {
            "id": 1,
            "name": "ESG 보고서 초안 작성",
            "problem": "공식자료 기반 보고서 초안 작성",
            "candidate_agent_name": "ESG Draft Agent",
            "target_user": "ESG 담당자",
            "security_level": "internal",
        }
    )

    assert result["compliance_level"] == "standard"
    assert result["korea_ai_basic_act_requirements"]
    assert "explainability_notice" in result["required_controls"]


def test_high_impact_process_includes_enhanced_korea_requirements():
    result = classify_process(
        {
            "id": 2,
            "name": "채용 지원자 평가",
            "problem": "지원자 평가 자동화",
            "candidate_agent_name": "HR Screening Agent",
            "target_user": "인사팀",
            "security_level": "confidential",
        }
    )

    assert result["compliance_level"] == "enhanced_review"
    assert result["human_review_required"] is True
    assert any("고영향" in item for item in result["korea_ai_basic_act_requirements"])


def test_assessment_exposes_korea_ai_basic_act_reference():
    assessment = assess_ai_compliance([
        {
            "id": 3,
            "name": "고객 FAQ 자동 응답 초안",
            "problem": "FAQ 답변 초안 작성",
            "candidate_agent_name": "FAQ Agent",
            "target_user": "고객지원팀",
            "security_level": "internal",
        }
    ])

    assert "korea_ai_basic_act_reference" in assessment
    assert get_korea_ai_basic_act_reference()["status"] == "operational_mapping_not_legal_advice"
    control_ids = {item["id"] for item in get_regulatory_controls()}
    assert "explainability_notice" in control_ids
    assert "safety_reliability_management" in control_ids
