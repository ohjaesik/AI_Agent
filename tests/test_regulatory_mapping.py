from app.compliance.assessment import assess_ai_compliance, classify_process
from app.compliance.regulatory_mapping import build_regulatory_mappings, summarize_regulatory_mappings


def test_prohibited_social_scoring_maps_to_blocked_regulation():
    item = classify_process(
        {
            "id": 1,
            "name": "사회적 점수 기반 고객 등급 자동화",
            "candidate_agent_name": "Social Scoring Agent",
        }
    )

    assert item["compliance_level"] == "blocked"
    assert item["blocked"] is True
    mapping_ids = {mapping["id"] for mapping in item["regulatory_mappings"]}
    assert "eu_ai_act_prohibited_use" in mapping_ids
    assert "prohibited_use_screening" in item["required_controls"]


def test_finance_credit_process_maps_to_enhanced_review_regulations():
    item = classify_process(
        {
            "id": 2,
            "name": "대출 신용 심사 지원",
            "candidate_agent_name": "Credit Risk Triage Agent",
        }
    )

    assert item["compliance_level"] == "enhanced_review"
    assert item["human_review_required"] is True
    mapping_ids = {mapping["id"] for mapping in item["regulatory_mappings"]}
    assert "eu_ai_act_high_risk" in mapping_ids
    assert "korea_ai_basic_act_high_impact" in mapping_ids
    assert "credit_finance_insurance" in item["regulatory_mappings"][0]["matched_triggers"]


def test_sensitive_customer_data_maps_to_privacy_controls():
    item = classify_process(
        {
            "id": 3,
            "name": "고객정보 기반 문의 요약",
            "candidate_agent_name": "Customer Insight Agent",
        }
    )

    assert item["compliance_level"] == "sensitive_review"
    assert item["human_review_required"] is True
    mapping_ids = {mapping["id"] for mapping in item["regulatory_mappings"]}
    assert "privacy_confidential_data" in mapping_ids
    assert "security_privacy_controls" in item["required_controls"]


def test_standard_process_keeps_baseline_assistive_mapping():
    item = classify_process(
        {
            "id": 4,
            "name": "제품 FAQ 문서 검색",
            "candidate_agent_name": "Product FAQ Assistant",
        }
    )

    assert item["compliance_level"] == "standard"
    assert item["human_review_required"] is False
    mapping_ids = {mapping["id"] for mapping in item["regulatory_mappings"]}
    assert mapping_ids == {"standard_assistive_ai"}
    assert "assistive_use_boundary" in item["required_controls"]


def test_assessment_summary_counts_frameworks_and_risk_categories():
    result = assess_ai_compliance(
        processes=[
            {"id": 1, "name": "제품 FAQ 문서 검색", "candidate_agent_name": "Product FAQ Assistant"},
            {"id": 2, "name": "대출 신용 심사 지원", "candidate_agent_name": "Credit Risk Triage Agent"},
        ]
    )

    assert result["overall_status"] == "review_required"
    assert result["summary"]["enhanced_review_count"] == 1
    assert result["summary"]["framework_counts"]["EU AI Act"] == 1
    assert result["summary"]["risk_category_counts"]["high_risk_ai_system"] == 1


def test_regulatory_mapping_summary_deduplicates_controls():
    mappings = build_regulatory_mappings(
        compliance_level="enhanced_review",
        prohibited_hits=[],
        high_impact_categories=["finance"],
        sensitive_hits=[],
        sensitive_risk_flags=[],
        high_impact_risk_flags=["financial_decision_support"],
        risk_flags=[],
    )
    summary = summarize_regulatory_mappings(mappings)

    assert "EU AI Act" in summary["frameworks"]
    assert "Korea AI Basic Act" in summary["frameworks"]
    assert summary["required_controls"].count("human_oversight") == 1
