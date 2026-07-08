# app/agents/registry.py

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentSpec:
    id: str
    name: str
    category: str
    purpose: str
    implementation: str
    inputs: list[str]
    outputs: list[str]
    tools: list[str] = field(default_factory=list)
    controls: list[str] = field(default_factory=list)
    human_review_required: bool = False
    regulatory_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


AGENT_REGISTRY: list[AgentSpec] = [
    AgentSpec(
        id="company_profile_agent",
        name="Company Profile Agent",
        category="input_and_context",
        purpose="회사명, OpenDART, 공식 URL을 기반으로 기업 식별 정보와 분석 범위를 구성한다.",
        implementation="tool_orchestrated",
        inputs=["company_name", "official_urls", "dart_api_key"],
        outputs=["company_profile", "analysis_project"],
        tools=["OpenDART client", "official URL loader", "Company DB writer"],
        controls=["official_source_only", "source_traceability", "raw_web_noise_filter"],
        regulatory_notes=[
            "투명성 확보를 위해 회사 프로필은 공식 출처 기반 필드와 출처 label로만 구성한다.",
            "웹 원문을 그대로 보고서에 노출하지 않고, RAG/출처 근거로만 보존한다.",
        ],
    ),
    AgentSpec(
        id="source_ingestion_agent",
        name="Source Ingestion Agent",
        category="input_and_context",
        purpose="공식 URL, PDF, DOCX, TXT 문서를 수집·정제·분할·임베딩하여 RAG 근거로 색인한다.",
        implementation="tool_based",
        inputs=["official_urls", "uploaded_files", "process_id"],
        outputs=["process_documents", "document_chunks", "used_sources"],
        tools=["document loader", "chunker", "embedding model", "pgvector"],
        controls=["data_minimization", "sensitive_info_detection", "document_level_access_control", "traceable_chunk_metadata"],
        regulatory_notes=[
            "고위험·민감 문서가 포함될 수 있으므로 문서별 보안등급과 민감정보 여부를 저장한다.",
            "검색 결과는 citation label과 source metadata로 추적 가능해야 한다.",
        ],
    ),
    AgentSpec(
        id="process_discovery_agent",
        name="Process Discovery Agent",
        category="llm_reasoning",
        purpose="공식자료에서 회사 특화 AX 후보 업무를 생성하고 근거 label, 적합성 근거, 점수 근거를 구조화한다.",
        implementation="llm_with_json_validation",
        inputs=["official_source_excerpts", "allowed_evidence_labels"],
        outputs=["business_processes", "discovery_metadata"],
        tools=["vLLM/Gemma", "JSON schema validation", "fallback template"],
        controls=["allowed_citation_labels_only", "no_unsupported_business_claims", "fallback_on_invalid_json"],
        regulatory_notes=[
            "생성형 AI 출력은 근거 label이 있는 후보만 저장하고, 실패 시 deterministic fallback을 사용한다.",
            "추천은 의사결정 확정이 아니라 Human Review 전 후보 생성으로 제한한다.",
        ],
    ),
    AgentSpec(
        id="process_analysis_agent",
        name="Process Analysis Agent",
        category="analysis",
        purpose="업무별 문제, 대상 사용자, 병목, 반복성, 문서 의존도, RAG 근거를 분석한다.",
        implementation="rule_plus_rag",
        inputs=["business_processes", "retrieved_contexts"],
        outputs=["process_analysis"],
        tools=["RAG retriever", "evidence collector"],
        controls=["evidence_required_for_key_claims", "audit_logging"],
        regulatory_notes=["업무 분석의 핵심 주장은 RAG 근거 또는 DB 필드에 연결한다."],
    ),
    AgentSpec(
        id="data_readiness_agent",
        name="Data Readiness Agent",
        category="analysis",
        purpose="데이터 접근성, 문서 품질, 권한 준비도를 평가한다.",
        implementation="deterministic_scoring",
        inputs=["business_processes", "documents"],
        outputs=["data_readiness"],
        controls=["data_quality_check", "access_precondition_check", "data_preparation_flag"],
        regulatory_notes=["데이터 품질과 접근권한은 고위험 AI 의무의 데이터 거버넌스 요구와 연결되는 선행 통제다."],
    ),
    AgentSpec(
        id="automation_feasibility_agent",
        name="Automation Feasibility Agent",
        category="analysis",
        purpose="Agent 적용 가능성과 예상 시간 절감률을 판단한다.",
        implementation="deterministic_scoring_with_discovery_rationale",
        inputs=["business_processes", "discovery_metadata"],
        outputs=["automation_feasibility"],
        controls=["assistive_only_by_default", "no_autonomous_execution", "rationale_logging"],
        regulatory_notes=["본 시스템은 업무 자동 실행이 아닌 판단 보조·추천형 Agent를 기본값으로 둔다."],
    ),
    AgentSpec(
        id="roi_cost_agent",
        name="ROI & Cost Agent",
        category="calculation",
        purpose="현재 비용, 예상 비용, 절감액, 절감률을 계산한다.",
        implementation="deterministic_calculation",
        inputs=["business_processes", "automation_feasibility"],
        outputs=["roi_cost"],
        controls=["formula_traceability", "no_llm_financial_guessing"],
        regulatory_notes=["재무성 추정은 고정 산식과 입력값 기반으로 계산하고 LLM 임의 추정을 금지한다."],
    ),
    AgentSpec(
        id="risk_governance_agent",
        name="Risk & Governance Agent",
        category="governance",
        purpose="보안, 개인정보, 기밀, 고영향 가능성, Human Review 필요성을 판단한다.",
        implementation="policy_rule_engine",
        inputs=["business_processes", "retrieved_contexts", "documents"],
        outputs=["risk_governance", "compliance_assessment"],
        controls=["prohibited_use_screening", "high_impact_screening", "human_oversight_required", "incident_logging"],
        human_review_required=True,
        regulatory_notes=[
            "금지영역 또는 고영향 가능성이 있으면 추천 자동 확정을 금지하고 Human Review로 전환한다.",
            "개인정보·기밀정보·채용·금융·의료·안전 관련 업무는 강화 통제를 적용한다.",
        ],
    ),
    AgentSpec(
        id="priority_delivery_agent",
        name="Priority & Delivery Agent",
        category="supervisor_output",
        purpose="우선순위 산정, Human Review, PoC 계획, 보고서 생성을 지휘한다.",
        implementation="supervisor_with_human_in_the_loop",
        inputs=["process_analysis", "data_readiness", "automation_feasibility", "roi_cost", "risk_governance", "compliance_assessment"],
        outputs=["priority_ranking", "human_review", "poc_plan", "report_data", "report_docx_path"],
        tools=["score calculator", "LangGraph interrupt", "report writer", "docx generator"],
        controls=["human_review_gate", "transparent_ai_disclosure", "citation_validation", "audit_trail"],
        human_review_required=True,
        regulatory_notes=[
            "최종 산출물은 AI 생성/보조 보고서임을 표시하고, Human Review 기록을 포함한다.",
            "PoC 착수는 추천 결과가 아니라 검토자 승인 기록을 기준으로 한다.",
        ],
    ),
]


def get_agent_registry() -> list[dict[str, Any]]:
    return [item.to_dict() for item in AGENT_REGISTRY]


def get_agent_spec(agent_id: str) -> dict[str, Any] | None:
    for item in AGENT_REGISTRY:
        if item.id == agent_id:
            return item.to_dict()
    return None
