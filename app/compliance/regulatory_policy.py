# app/compliance/regulatory_policy.py

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class RegulatoryControl:
    id: str
    name: str
    source_frameworks: list[str]
    purpose: str
    implementation_hint: str
    evidence_fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


REGULATORY_CONTROLS: list[RegulatoryControl] = [
    RegulatoryControl(
        id="prohibited_use_screening",
        name="Prohibited-use screening",
        source_frameworks=["EU AI Act", "Korea AI Basic Act"],
        purpose="사회적 점수화, 무차별 생체정보 수집, 취약성 악용 등 금지 또는 부적절한 AI 활용을 차단한다.",
        implementation_hint="업무명, 문제정의, 문서 내용에서 금지·민감 사용 키워드를 탐지하고, 발견 시 자동 추천을 차단한다.",
        evidence_fields=["risk_flags", "blocked_reasons", "human_review_required"],
    ),
    RegulatoryControl(
        id="high_impact_screening",
        name="High-impact AI screening",
        source_frameworks=["Korea AI Basic Act", "EU AI Act"],
        purpose="의료, 금융, 채용, 교통, 핵심 인프라, 안전 등 민감 영역의 AI 적용 가능성을 식별한다.",
        implementation_hint="업무 후보를 고영향 가능성 카테고리에 매핑하고 Human Review 및 강화 통제 조건을 부여한다.",
        evidence_fields=["high_impact_categories", "required_controls"],
    ),
    RegulatoryControl(
        id="human_oversight",
        name="Human oversight",
        source_frameworks=["EU AI Act", "Korea AI Basic Act", "NIST AI RMF"],
        purpose="AI 추천이 최종 의사결정으로 오인되지 않도록 사람의 검토와 승인 기록을 남긴다.",
        implementation_hint="priority ranking 이후 LangGraph interrupt를 통해 approve/edit/reject 결정을 기록한다.",
        evidence_fields=["human_review", "reviewer_name", "decision", "comment"],
    ),
    RegulatoryControl(
        id="transparency_disclosure",
        name="AI transparency and disclosure",
        source_frameworks=["EU AI Act", "Korea AI Basic Act", "ISO/IEC 42001"],
        purpose="사용자가 AI 생성/보조 산출물임을 인지하도록 문서 상태, 생성방식, citation validation을 표시한다.",
        implementation_hint="보고서 표지·footer·Human Review 섹션에 AI 보조 산출물임을 표시한다.",
        evidence_fields=["report_status", "generation.mode", "citation_validation"],
    ),
    RegulatoryControl(
        id="traceability_logging",
        name="Traceability and logging",
        source_frameworks=["EU AI Act", "NIST AI RMF", "ISO/IEC 42001"],
        purpose="AI 판단 근거와 실행 이력을 추적할 수 있게 한다.",
        implementation_hint="각 node 결과, evidence label, used_sources, audit_logs를 저장한다.",
        evidence_fields=["audit_logs", "used_sources", "evidence_items", "analysis_results"],
    ),
    RegulatoryControl(
        id="data_quality_governance",
        name="Data quality and governance",
        source_frameworks=["EU AI Act", "NIST AI RMF", "ISO/IEC 42001"],
        purpose="부정확하거나 권한 없는 데이터로 후보 판단이 이뤄지지 않도록 데이터 준비도를 평가한다.",
        implementation_hint="문서 보안등급, 민감정보 여부, data_accessibility, RAG 근거 수를 평가한다.",
        evidence_fields=["data_readiness", "document.security_level", "contains_sensitive_info"],
    ),
    RegulatoryControl(
        id="security_privacy_controls",
        name="Security and privacy controls",
        source_frameworks=["EU AI Act", "NIST AI RMF", "ISO/IEC 42001"],
        purpose="개인정보, 영업비밀, 지식재산, 보안 문서가 포함된 업무에 강화 통제를 적용한다.",
        implementation_hint="risk_flags와 문서 민감도에 따라 data_preparation_required 또는 human_review_required 상태를 부여한다.",
        evidence_fields=["risk_governance", "risk_flags", "security_level"],
    ),
    RegulatoryControl(
        id="assistive_use_boundary",
        name="Assistive-use boundary",
        source_frameworks=["NIST AI RMF", "ISO/IEC 42001"],
        purpose="AX Planner가 업무 자동 실행 시스템이 아니라 PoC 후보 추천·판단 보조 시스템임을 명확히 한다.",
        implementation_hint="모든 후보의 type을 assistive_ai_agent로 설정하고 자동 실행 권한을 부여하지 않는다.",
        evidence_fields=["mvp_agent.type", "poc_plan.entry_criteria"],
    ),
]


def get_regulatory_controls() -> list[dict[str, Any]]:
    return [item.to_dict() for item in REGULATORY_CONTROLS]


def get_control(control_id: str) -> dict[str, Any] | None:
    for item in REGULATORY_CONTROLS:
        if item.id == control_id:
            return item.to_dict()
    return None
