# app/compliance/regulatory_mapping.py

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class RegulatoryMappingRule:
    id: str
    framework: str
    risk_category: str
    applies_when: str
    control_level: str
    required_controls: list[str]
    obligations: list[str]
    evidence_fields: list[str] = field(default_factory=list)
    implementation_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


REGULATORY_MAPPING_RULES: dict[str, RegulatoryMappingRule] = {
    "eu_ai_act_prohibited_use": RegulatoryMappingRule(
        id="eu_ai_act_prohibited_use",
        framework="EU AI Act",
        risk_category="unacceptable_risk_prohibited_practice",
        applies_when="social scoring, manipulative or exploitative AI, prohibited biometric use, predictive policing, or similar prohibited use is detected",
        control_level="blocked",
        required_controls=["prohibited_use_screening", "human_oversight", "traceability_logging"],
        obligations=[
            "Exclude from MVP and PoC candidate list.",
            "Require legal owner review before any further analysis.",
            "Record trigger keywords and blocked reason.",
        ],
        evidence_fields=["prohibited_hits", "risk_flags", "blocked"],
        implementation_note="Operational proxy for EU AI Act prohibited-practice screening. It is not a final legal classification.",
    ),
    "eu_ai_act_high_risk": RegulatoryMappingRule(
        id="eu_ai_act_high_risk",
        framework="EU AI Act",
        risk_category="high_risk_ai_system",
        applies_when="AI is used in employment, finance/credit, healthcare, education, critical infrastructure, justice, public service, or similar high-impact context",
        control_level="enhanced_review",
        required_controls=[
            "high_impact_screening",
            "human_oversight",
            "data_quality_governance",
            "safety_reliability_management",
            "traceability_logging",
            "explainability_notice",
        ],
        obligations=[
            "Do not allow autonomous final decisions.",
            "Require human oversight and accountable owner sign-off.",
            "Document data quality, evidence sources, limitations, and evaluation results.",
            "Keep audit logs and reviewer decision records.",
        ],
        evidence_fields=["high_impact_categories", "high_impact_risk_flags", "required_controls"],
        implementation_note="Maps high-impact business domains to enhanced review obligations inspired by EU AI Act high-risk controls.",
    ),
    "korea_ai_basic_act_high_impact": RegulatoryMappingRule(
        id="korea_ai_basic_act_high_impact",
        framework="Korea AI Basic Act",
        risk_category="high_impact_ai_operational_proxy",
        applies_when="AI may significantly affect life, safety, fundamental rights, employment, finance, healthcare, critical infrastructure, education, or public services",
        control_level="enhanced_review",
        required_controls=[
            "high_impact_screening",
            "human_oversight",
            "transparency_disclosure",
            "explainability_notice",
            "data_quality_governance",
            "safety_reliability_management",
        ],
        obligations=[
            "Screen for high-impact AI before PoC approval.",
            "Provide AI-use notice and explainability record where user impact exists.",
            "Designate human owner and prevent AI-only final decisions.",
            "Prepare safety, reliability, data quality, and traceability evidence.",
        ],
        evidence_fields=["high_impact_categories", "human_review_required", "korea_ai_basic_act_requirements"],
        implementation_note="Operational mapping for Korean AI governance. Official law, enforcement decree, and regulatory guidance must be checked before production use.",
    ),
    "privacy_confidential_data": RegulatoryMappingRule(
        id="privacy_confidential_data",
        framework="Privacy/Security Governance",
        risk_category="personal_or_confidential_data_processing",
        applies_when="personal data, account data, credential, customer information, trade secret, or confidential document context is detected",
        control_level="sensitive_review",
        required_controls=[
            "security_privacy_controls",
            "data_quality_governance",
            "human_oversight",
            "traceability_logging",
        ],
        obligations=[
            "Apply data minimization and access control.",
            "Separate sensitive evidence from public report output.",
            "Require security or data owner review before PoC execution.",
        ],
        evidence_fields=["sensitive_hits", "sensitive_risk_flags", "security_level"],
        implementation_note="Covers personal, confidential, and restricted-access data handling controls.",
    ),
    "standard_assistive_ai": RegulatoryMappingRule(
        id="standard_assistive_ai",
        framework="Korea AI Basic Act / NIST AI RMF / ISO 42001",
        risk_category="standard_assistive_ai",
        applies_when="AI is used as an assistive planning or reporting tool without high-impact, sensitive, or prohibited triggers",
        control_level="standard",
        required_controls=[
            "transparency_disclosure",
            "explainability_notice",
            "traceability_logging",
            "assistive_use_boundary",
        ],
        obligations=[
            "Disclose that output is AI-assisted.",
            "Keep evidence labels, source references, and generation mode.",
            "Maintain assistive-use boundary and do not execute final business decisions automatically.",
        ],
        evidence_fields=["report_requirements", "evidence_labels", "audit_logs"],
        implementation_note="Baseline governance mapping for ordinary AI-assisted planning outputs.",
    ),
}


HIGH_IMPACT_TO_REGULATORY_DOMAIN = {
    "employment": "employment_worker_management",
    "finance": "credit_finance_insurance",
    "healthcare": "healthcare_medical_triage",
    "critical_infrastructure": "critical_infrastructure_safety",
    "education": "education_access_assessment",
    "law_public_service": "law_public_service_access",
    "safety_critical": "critical_infrastructure_safety",
    "legal_decision_support": "law_public_service_access",
    "employment_decision_support": "employment_worker_management",
    "financial_decision_support": "credit_finance_insurance",
    "medical_decision_support": "healthcare_medical_triage",
}


def _mapping_payload(rule_id: str, matched_triggers: list[str]) -> dict[str, Any]:
    rule = REGULATORY_MAPPING_RULES[rule_id]
    payload = rule.to_dict()
    payload["matched_triggers"] = sorted(set(str(item) for item in matched_triggers if str(item).strip()))
    return payload


def build_regulatory_mappings(
    *,
    compliance_level: str,
    prohibited_hits: list[str],
    high_impact_categories: list[str],
    sensitive_hits: list[str],
    sensitive_risk_flags: list[str],
    high_impact_risk_flags: list[str],
    risk_flags: list[str],
) -> list[dict[str, Any]]:
    mappings: list[dict[str, Any]] = []

    if prohibited_hits or compliance_level == "blocked":
        mappings.append(_mapping_payload("eu_ai_act_prohibited_use", prohibited_hits or risk_flags))

    high_impact_triggers = sorted(set(high_impact_categories + high_impact_risk_flags))
    if high_impact_triggers or compliance_level == "enhanced_review":
        domain_triggers = [HIGH_IMPACT_TO_REGULATORY_DOMAIN.get(item, item) for item in high_impact_triggers]
        mappings.append(_mapping_payload("eu_ai_act_high_risk", domain_triggers or [compliance_level]))
        mappings.append(_mapping_payload("korea_ai_basic_act_high_impact", domain_triggers or [compliance_level]))

    sensitive_triggers = sorted(set(sensitive_hits + sensitive_risk_flags))
    if sensitive_triggers or compliance_level == "sensitive_review":
        mappings.append(_mapping_payload("privacy_confidential_data", sensitive_triggers or [compliance_level]))

    if not mappings:
        mappings.append(_mapping_payload("standard_assistive_ai", ["standard_assistive_use"]))

    return mappings


def summarize_regulatory_mappings(mappings: list[dict[str, Any]]) -> dict[str, Any]:
    frameworks: list[str] = []
    risk_categories: list[str] = []
    required_controls: list[str] = []
    obligations: list[str] = []

    for mapping in mappings:
        framework = str(mapping.get("framework") or "")
        risk_category = str(mapping.get("risk_category") or "")
        if framework and framework not in frameworks:
            frameworks.append(framework)
        if risk_category and risk_category not in risk_categories:
            risk_categories.append(risk_category)
        for control in mapping.get("required_controls", []) or []:
            if control not in required_controls:
                required_controls.append(control)
        for obligation in mapping.get("obligations", []) or []:
            if obligation not in obligations:
                obligations.append(obligation)

    return {
        "frameworks": frameworks,
        "risk_categories": risk_categories,
        "required_controls": required_controls,
        "obligations": obligations,
    }


def get_regulatory_mapping_rules() -> list[dict[str, Any]]:
    return [rule.to_dict() for rule in REGULATORY_MAPPING_RULES.values()]
