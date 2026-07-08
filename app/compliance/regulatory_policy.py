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
    korea_ai_basic_act_mapping: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


KOREA_AI_BASIC_ACT_REFERENCE = {
    "status": "operational_mapping_not_legal_advice",
    "effective_context": "보도 기준 2026년 시행 및 유예기간 전제로 관리. 공식 조문·시행령·고시 확정본은 운영 전 재확인 필요.",
    "core_themes": [
        "고영향 AI 식별 및 관리",
        "사람의 감독과 최종 책임",
        "AI 생성물 또는 AI 사용 사실의 고지·표시",
        "설명가능성 및 이용자 권리 보호",
        "안전성·신뢰성 확보",
        "사업자 책임과 문서화",
    ],
}


REGULATORY_CONTROLS: list[RegulatoryControl] = [
    RegulatoryControl(
        id="prohibited_use_screening",
        name="Prohibited-use screening",
        source_frameworks=["EU AI Act", "Korea AI Basic Act"],
        purpose="사회적 점수화, 무차별 생체정보 수집, 취약성 악용 등 금지 또는 부적절한 AI 활용을 차단한다.",
        implementation_hint="업무명, 문제정의, 문서 내용에서 금지·민감 사용 키워드를 탐지하고, 발견 시 자동 추천을 차단한다.",
        evidence_fields=["risk_flags", "blocked_reasons", "human_review_required"],
        korea_ai_basic_act_mapping=[
            "부적절하거나 고위험성이 큰 AI 활용을 사전에 걸러내기 위한 내부 통제",
            "고영향 AI 여부 판단 전 단계의 misuse screening",
        ],
    ),
    RegulatoryControl(
        id="high_impact_screening",
        name="High-impact AI screening",
        source_frameworks=["Korea AI Basic Act", "EU AI Act"],
        purpose="의료, 금융, 채용, 교통, 핵심 인프라, 안전 등 민감 영역의 AI 적용 가능성을 식별한다.",
        implementation_hint="업무 후보를 고영향 가능성 카테고리에 매핑하고 Human Review 및 강화 통제 조건을 부여한다.",
        evidence_fields=["high_impact_categories", "required_controls"],
        korea_ai_basic_act_mapping=[
            "고영향 AI에 해당할 수 있는 영역의 사전 식별",
            "의료·금융·채용·교통·핵심 인프라·안전 관련 후보의 enhanced_review 분류",
        ],
    ),
    RegulatoryControl(
        id="human_oversight",
        name="Human oversight",
        source_frameworks=["EU AI Act", "Korea AI Basic Act", "NIST AI RMF"],
        purpose="AI 추천이 최종 의사결정으로 오인되지 않도록 사람의 검토와 승인 기록을 남긴다.",
        implementation_hint="priority ranking 이후 LangGraph interrupt를 통해 approve/edit/reject 결정을 기록한다.",
        evidence_fields=["human_review", "reviewer_name", "decision", "comment"],
        korea_ai_basic_act_mapping=[
            "고영향 AI 또는 민감 후보에 대한 사람 감독 원칙",
            "AI 산출물이 직접 의사결정으로 사용되지 않도록 최종 승인자를 기록",
        ],
    ),
    RegulatoryControl(
        id="transparency_disclosure",
        name="AI transparency and disclosure",
        source_frameworks=["EU AI Act", "Korea AI Basic Act", "ISO/IEC 42001"],
        purpose="사용자가 AI 생성/보조 산출물임을 인지하도록 문서 상태, 생성방식, citation validation을 표시한다.",
        implementation_hint="보고서 표지·footer·Human Review 섹션에 AI 보조 산출물임을 표시한다.",
        evidence_fields=["report_status", "generation.mode", "citation_validation"],
        korea_ai_basic_act_mapping=[
            "AI 생성물 또는 AI 보조 산출물임을 이용자가 인지할 수 있도록 고지",
            "보고서 상태 draft/reviewed/final 및 생성 방식 표시",
        ],
    ),
    RegulatoryControl(
        id="explainability_notice",
        name="Explainability and user notice",
        source_frameworks=["Korea AI Basic Act", "EU AI Act", "NIST AI RMF"],
        purpose="추천 이유, 근거 source, 제한사항을 보고서와 검토 payload에 표시한다.",
        implementation_hint="candidate별 score_rationale, evidence_labels, confidence_score, reviewer decision을 함께 저장한다.",
        evidence_fields=["score_rationale", "evidence_labels", "agent_evaluation", "human_review"],
        korea_ai_basic_act_mapping=[
            "고영향 또는 이용자 영향이 있는 AI 결과에 대해 설명가능성 확보",
            "AI 추천의 근거와 한계를 이용자·검토자가 확인 가능하도록 제공",
        ],
    ),
    RegulatoryControl(
        id="traceability_logging",
        name="Traceability and logging",
        source_frameworks=["EU AI Act", "NIST AI RMF", "ISO/IEC 42001", "Korea AI Basic Act"],
        purpose="AI 판단 근거와 실행 이력을 추적할 수 있게 한다.",
        implementation_hint="각 node 결과, evidence label, used_sources, audit_logs를 저장한다.",
        evidence_fields=["audit_logs", "used_sources", "evidence_items", "analysis_results"],
        korea_ai_basic_act_mapping=[
            "신뢰성 확보 및 사후 검토를 위한 문서화·기록 관리",
            "AI 사업자 책임 및 내부 관리체계 증빙",
        ],
    ),
    RegulatoryControl(
        id="data_quality_governance",
        name="Data quality and governance",
        source_frameworks=["EU AI Act", "NIST AI RMF", "ISO/IEC 42001", "Korea AI Basic Act"],
        purpose="부정확하거나 권한 없는 데이터로 후보 판단이 이뤄지지 않도록 데이터 준비도를 평가한다.",
        implementation_hint="문서 보안등급, 민감정보 여부, data_accessibility, RAG 근거 수를 평가한다.",
        evidence_fields=["data_readiness", "document.security_level", "contains_sensitive_info"],
        korea_ai_basic_act_mapping=[
            "AI 신뢰성 확보를 위한 데이터 품질·출처·접근권한 관리",
            "공식자료와 내부 문서 근거의 분리 및 citation 추적",
        ],
    ),
    RegulatoryControl(
        id="security_privacy_controls",
        name="Security and privacy controls",
        source_frameworks=["EU AI Act", "NIST AI RMF", "ISO/IEC 42001", "Korea AI Basic Act"],
        purpose="개인정보, 영업비밀, 지식재산, 보안 문서가 포함된 업무에 강화 통제를 적용한다.",
        implementation_hint="risk_flags와 문서 민감도에 따라 data_preparation_required 또는 human_review_required 상태를 부여한다.",
        evidence_fields=["risk_governance", "risk_flags", "security_level"],
        korea_ai_basic_act_mapping=[
            "AI 시스템 안전성·신뢰성 확보와 개인정보·민감정보 보호",
            "민감정보 포함 후보의 sensitive_review 분류 및 접근권한 관리",
        ],
    ),
    RegulatoryControl(
        id="safety_reliability_management",
        name="Safety and reliability management",
        source_frameworks=["Korea AI Basic Act", "NIST AI RMF", "ISO/IEC 42001"],
        purpose="AI Agent가 낮은 근거·낮은 confidence 상태에서 추천을 확정하지 않도록 품질 gate를 적용한다.",
        implementation_hint="Agent Evaluator, LLM Critic, Replan Loop, quality eval gate로 후보 신뢰도를 관리한다.",
        evidence_fields=["agent_evaluation", "llm_critic", "replan_request", "quality_gate"],
        korea_ai_basic_act_mapping=[
            "신뢰 가능한 AI 이용을 위한 안전성·신뢰성 관리",
            "고영향 가능 후보에 대해 confidence/evidence 부족 시 자동 추천 금지",
        ],
    ),
    RegulatoryControl(
        id="assistive_use_boundary",
        name="Assistive-use boundary",
        source_frameworks=["NIST AI RMF", "ISO/IEC 42001", "Korea AI Basic Act"],
        purpose="AX Planner가 업무 자동 실행 시스템이 아니라 PoC 후보 추천·판단 보조 시스템임을 명확히 한다.",
        implementation_hint="모든 후보의 type을 assistive_ai_agent로 설정하고 자동 실행 권한을 부여하지 않는다.",
        evidence_fields=["mvp_agent.type", "poc_plan.entry_criteria"],
        korea_ai_basic_act_mapping=[
            "AI가 최종 업무 결정을 대체하지 않고 사람의 판단을 보조하는 범위로 제한",
            "자동 실행·자동 처분·자동 승인 기능 미제공",
        ],
    ),
]


def get_regulatory_controls() -> list[dict[str, Any]]:
    return [item.to_dict() for item in REGULATORY_CONTROLS]


def get_control(control_id: str) -> dict[str, Any] | None:
    for item in REGULATORY_CONTROLS:
        if item.id == control_id:
            return item.to_dict()
    return None


def get_korea_ai_basic_act_reference() -> dict[str, Any]:
    return KOREA_AI_BASIC_ACT_REFERENCE
