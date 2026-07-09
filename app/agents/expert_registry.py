# app/agents/expert_registry.py

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ExpertAgentSpec:
    id: str
    name: str
    category: str
    purpose: str
    implementation: str
    managed_nodes: list[str]
    capabilities: list[dict[str, Any]]
    tools: list[str] = field(default_factory=list)
    controls: list[str] = field(default_factory=list)
    human_review_required: bool = False
    quality_checks: list[str] = field(default_factory=list)
    output_contract: list[str] = field(default_factory=list)
    handoff_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


EXPERT_AGENT_REGISTRY: list[ExpertAgentSpec] = [
    ExpertAgentSpec(
        id="company_onboarding_agent",
        name="Company Onboarding Agent",
        category="input_and_context",
        purpose="회사명, 공식 URL, OpenDART 정보를 기반으로 분석 대상 기업과 초기 업무 후보를 구성한다.",
        implementation="supervisor_tool_orchestrated_with_llm_discovery",
        managed_nodes=[
            "company_profile_agent",
            "source_ingestion_agent",
            "process_discovery_agent",
        ],
        capabilities=[
            {
                "name": "company_profile_resolution",
                "node_role": "회사 식별, OpenDART 조회, company profile 생성/갱신",
                "nodes": ["company_profile_agent"],
            },
            {
                "name": "official_source_ingestion",
                "node_role": "공식 URL과 공시 자료 수집, 문서 저장, RAG 색인 준비",
                "nodes": ["source_ingestion_agent"],
            },
            {
                "name": "process_candidate_discovery",
                "node_role": "공식자료 기반 AX 후보 업무 생성과 evidence label 연결",
                "nodes": ["process_discovery_agent"],
            },
        ],
        tools=["OpenDART client", "official URL loader", "document indexer", "vLLM/Gemma", "JSON schema validation"],
        controls=["official_source_only", "source_traceability", "allowed_citation_labels_only", "fallback_on_invalid_json"],
        human_review_required=False,
        quality_checks=[
            "회사 profile과 업무 후보는 공식 URL, OpenDART, 사용자 입력에 근거해야 한다.",
            "LLM이 생성한 후보는 allowed evidence label과 schema 검증을 통과해야 한다.",
            "공식 근거가 없거나 JSON이 깨진 경우 deterministic fallback을 사용한다.",
        ],
        output_contract=[
            "company_id, project_id, document_ids, process_ids를 생성하거나 재사용한다.",
            "공식 출처와 discovery metadata를 downstream graph에서 추적 가능하게 남긴다.",
        ],
        handoff_notes=["Context & Evidence Agent에 company/project/document/process id를 넘긴다."],
    ),
    ExpertAgentSpec(
        id="context_evidence_agent",
        name="Context & Evidence Agent",
        category="rag_and_evidence",
        purpose="DB에 저장된 분석 context를 로드하고, 업무별 RAG 근거와 citation source를 구성한다.",
        implementation="tool_based_rag_retrieval",
        managed_nodes=["load_project_data", "retrieve_context"],
        capabilities=[
            {
                "name": "project_context_loading",
                "node_role": "project, company, process, document, system 정보를 DB에서 로드",
                "nodes": ["load_project_data"],
            },
            {
                "name": "rag_evidence_retrieval",
                "node_role": "업무별 pgvector 검색, evidence item 생성, used_sources 구성",
                "nodes": ["retrieve_context"],
            },
        ],
        tools=["PostgreSQL", "pgvector retriever", "evidence collector"],
        controls=["traceable_chunk_metadata", "citation_label_preservation", "document_access_boundary"],
        human_review_required=False,
        quality_checks=[
            "모든 evidence item은 document/chunk/source metadata로 추적 가능해야 한다.",
            "근거가 없으면 RAG 근거 없음으로 명시하고 confidence를 올리지 않는다.",
            "used_sources는 중복 제거되어야 한다.",
        ],
        output_contract=[
            "retrieved_contexts, evidence_items, used_sources를 생성한다.",
            "downstream analysis node가 citation label을 참조할 수 있게 한다.",
        ],
        handoff_notes=["Process Diagnosis, Governance, Evaluation, Report 단계에 evidence state를 전달한다."],
    ),
    ExpertAgentSpec(
        id="process_diagnosis_agent",
        name="Process Diagnosis Agent",
        category="analysis",
        purpose="업무별 병목, 데이터 준비도, 자동화 보조 가능성을 진단한다.",
        implementation="rule_plus_rag_deterministic_scoring",
        managed_nodes=["process_analyzer", "data_readiness", "automation_feasibility"],
        capabilities=[
            {
                "name": "process_bottleneck_analysis",
                "node_role": "업무 문제, 대상 사용자, 현재 흐름, 문서 의존성, 근거 요약",
                "nodes": ["process_analyzer"],
            },
            {
                "name": "data_readiness_scoring",
                "node_role": "데이터 접근성, 문서 연결성, 접근권한 기반 readiness 분류",
                "nodes": ["data_readiness"],
            },
            {
                "name": "automation_feasibility_scoring",
                "node_role": "반복성, 기대효과, 구현 가능성, 위험도 기반 assistive automation 가능성 계산",
                "nodes": ["automation_feasibility"],
            },
        ],
        tools=["RAG context reader", "deterministic score calculator"],
        controls=["evidence_required_for_key_claims", "data_preparation_flag", "assistive_only_by_default"],
        human_review_required=False,
        quality_checks=[
            "업무 후보를 새로 만들지 않고 입력된 business_processes만 분석한다.",
            "data_accessibility가 낮은 후보를 high readiness로 올리지 않는다.",
            "자동 실행이 아니라 추천, 검색, drafting, triage, monitoring 등 보조 범위로 제한한다.",
        ],
        output_contract=[
            "process_analysis, data_readiness, automation_feasibility를 생성한다.",
            "각 후보에 process_id 기반으로 downstream ranking 가능한 항목을 남긴다.",
        ],
        handoff_notes=["Business Case Agent와 Governance Agent에 진단 결과를 전달한다."],
    ),
    ExpertAgentSpec(
        id="business_case_agent",
        name="Business Case Agent",
        category="calculation_and_prioritization",
        purpose="업무 후보의 비용 절감 가능성과 PoC 우선순위를 산정한다.",
        implementation="deterministic_calculation_and_weighted_ranking",
        managed_nodes=["roi_cost", "priority_ranking"],
        capabilities=[
            {
                "name": "roi_cost_calculation",
                "node_role": "현재 비용, 예상 비용, 절감률, PoC 비용 계산",
                "nodes": ["roi_cost"],
            },
            {
                "name": "candidate_priority_ranking",
                "node_role": "효과, 반복성, readiness, ROI, risk 기반 우선순위 산정",
                "nodes": ["priority_ranking"],
            },
        ],
        tools=["ROI calculator", "score calculator"],
        controls=["formula_traceability", "no_llm_financial_guessing", "bounded_score_weights"],
        human_review_required=False,
        quality_checks=[
            "재무성 추정은 LLM 추정이 아니라 고정 산식과 입력값 기반으로 계산한다.",
            "ROI는 확정 투자성과가 아니라 PoC 우선순위 판단 보조값으로 표시한다.",
            "blocked 또는 evidence_insufficient 후보가 최우선 추천으로 남지 않도록 downstream evaluator에 넘긴다.",
        ],
        output_contract=[
            "roi_cost와 priority_ranking을 생성한다.",
            "ranking item은 final_score, saving_rate, status, rationale, risk flags를 포함해야 한다.",
        ],
        handoff_notes=["Evaluation & Critic Agent가 ranking을 재검증한다."],
    ),
    ExpertAgentSpec(
        id="governance_compliance_agent",
        name="Governance & Compliance Agent",
        category="governance",
        purpose="보안, 개인정보, 기밀, 고영향 가능성, 금지 가능 사용을 점검한다.",
        implementation="policy_rule_engine_with_regulatory_mapping",
        managed_nodes=["risk_governance", "compliance_assessment"],
        capabilities=[
            {
                "name": "risk_signal_screening",
                "node_role": "업무명, 문제, workflow, 문서, RAG context에서 risk flag 탐지",
                "nodes": ["risk_governance"],
            },
            {
                "name": "regulatory_mapping",
                "node_role": "EU AI Act, Korea AI Basic Act proxy, privacy/security mapping 생성",
                "nodes": ["compliance_assessment"],
            },
        ],
        tools=["policy rule engine", "regulatory mapping rules"],
        controls=["prohibited_use_screening", "high_impact_screening", "human_oversight_required", "incident_logging"],
        human_review_required=True,
        quality_checks=[
            "금지 가능 후보는 excluded로 전환되어야 한다.",
            "고영향 또는 민감정보 후보는 Human Review를 요구해야 한다.",
            "위험 후보는 ROI가 높아도 governance 요구사항을 낮추지 않는다.",
        ],
        output_contract=[
            "risk_governance와 compliance_assessment를 생성한다.",
            "blocked, human_review_required, required_controls, regulatory_mappings를 명시한다.",
        ],
        handoff_notes=["Evaluation & Critic Agent와 Delivery Orchestration Agent에 compliance 결과를 전달한다."],
    ),
    ExpertAgentSpec(
        id="evaluation_critic_agent",
        name="Evaluation & Critic Agent",
        category="evaluation",
        purpose="우선순위 결과의 근거 충분성, confidence, compliance alignment를 재검증하고 필요 시 replan을 수행한다.",
        implementation="deterministic_quality_gate_with_optional_llm_critic",
        managed_nodes=["agent_evaluator", "llm_critic", "agent_replan"],
        capabilities=[
            {
                "name": "deterministic_agent_evaluation",
                "node_role": "evidence coverage, data confidence, rationale coverage, compliance alignment 계산",
                "nodes": ["agent_evaluator"],
            },
            {
                "name": "llm_second_opinion",
                "node_role": "LLM 기반 보조 검토와 confidence calibration",
                "nodes": ["llm_critic"],
            },
            {
                "name": "bounded_replan",
                "node_role": "추가 근거가 유효할 때 제한된 replan loop 수행",
                "nodes": ["agent_replan"],
            },
        ],
        tools=["evidence coverage scorer", "LLM critic", "quality gate", "replan router"],
        controls=["no_recommendation_without_evidence", "compliance_alignment_check", "confidence_thresholding", "bounded_replan_loop"],
        human_review_required=True,
        quality_checks=[
            "근거가 매우 약한 후보는 recommended가 아니라 evidence_insufficient가 되어야 한다.",
            "LLM critic 실패 시 deterministic evaluation을 source of truth로 유지한다.",
            "replan은 configured max attempts 안에서만 수행한다.",
        ],
        output_contract=[
            "agent_evaluation과 평가 후 priority_ranking status를 생성한다.",
            "LLM critic 결과는 llm_quality_eval에서 검증 가능한 schema를 유지한다.",
        ],
        handoff_notes=["Human Review와 Delivery 단계에 보수적으로 재분류된 후보를 전달한다."],
    ),
    ExpertAgentSpec(
        id="delivery_orchestration_agent",
        name="Delivery Orchestration Agent",
        category="supervisor_output",
        purpose="Human Review 이후 승인 후보를 PoC 계획과 보고서 산출물로 전환한다.",
        implementation="human_in_the_loop_delivery_supervisor",
        managed_nodes=["human_review", "poc_delivery_planner", "report_writer", "docx_generator"],
        capabilities=[
            {
                "name": "human_review_gate",
                "node_role": "approve/edit/reject 검토 기록 수집과 graph resume",
                "nodes": ["human_review"],
            },
            {
                "name": "poc_delivery_planning",
                "node_role": "승인 후보 기반 6주 PoC 계획, milestone, KPI 생성",
                "nodes": ["poc_delivery_planner"],
            },
            {
                "name": "report_generation",
                "node_role": "근거 기반 report_data 생성, LLM 문장화, citation validation",
                "nodes": ["report_writer"],
            },
            {
                "name": "docx_export",
                "node_role": "report_data를 DOCX 파일로 내보내기",
                "nodes": ["docx_generator"],
            },
        ],
        tools=["LangGraph interrupt", "report writer", "citation validator", "docx generator"],
        controls=["human_review_gate", "transparent_ai_disclosure", "citation_validation", "audit_trail"],
        human_review_required=True,
        quality_checks=[
            "승인 기록 없이 final-status 보고서를 생성하지 않는다.",
            "excluded 또는 evidence_insufficient 후보를 첫 PoC 대상으로 선택하지 않는다.",
            "보고서 참고문헌과 citation은 used_sources 또는 evidence_items에 연결되어야 한다.",
        ],
        output_contract=[
            "human_review, poc_plan, report_data, report_docx_path를 생성한다.",
            "보고서는 review status, AI-use disclosure, citation validation 결과를 포함해야 한다.",
        ],
        handoff_notes=["CLI/API 응답에 report_docx_path와 workflow state를 반환한다."],
    ),
]


def get_expert_agent_registry() -> list[dict[str, Any]]:
    return [item.to_dict() for item in EXPERT_AGENT_REGISTRY]


def get_expert_agent_spec(agent_id: str) -> dict[str, Any] | None:
    for item in EXPERT_AGENT_REGISTRY:
        if item.id == agent_id:
            return item.to_dict()
    return None


def get_capability_for_node(agent_spec: dict[str, Any], node_name: str) -> dict[str, Any] | None:
    for capability in agent_spec.get("capabilities", []) or []:
        if node_name in capability.get("nodes", []):
            return dict(capability)
    return None
