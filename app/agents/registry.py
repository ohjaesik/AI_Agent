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
    managed_nodes: list[str]
    capabilities: list[dict[str, Any]]
    tools: list[str] = field(default_factory=list)
    controls: list[str] = field(default_factory=list)
    human_review_required: bool = False
    regulatory_notes: list[str] = field(default_factory=list)
    role_prompt: str = ""
    task_instructions: list[str] = field(default_factory=list)
    quality_checks: list[str] = field(default_factory=list)
    output_contract: list[str] = field(default_factory=list)
    handoff_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


AGENT_REGISTRY: list[AgentSpec] = [
    AgentSpec(
        id="company_onboarding_agent",
        name="Company Onboarding Agent",
        category="input_and_context",
        purpose="회사명, 공식 URL, OpenDART 정보를 기반으로 분석 대상 기업과 초기 업무 후보를 구성한다.",
        implementation="supervisor_tool_orchestrated_with_llm_discovery",
        managed_nodes=["company_profile_agent", "source_ingestion_agent", "process_discovery_agent"],
        capabilities=[
            {"name": "company_profile_resolution", "node_role": "회사 식별, OpenDART 조회, company profile 생성/갱신", "nodes": ["company_profile_agent"]},
            {"name": "official_source_ingestion", "node_role": "공식 URL과 공시 자료 수집, 문서 저장, RAG 색인 준비", "nodes": ["source_ingestion_agent"]},
            {"name": "process_candidate_discovery", "node_role": "공식자료 기반 AX 후보 업무 생성과 evidence label 연결", "nodes": ["process_discovery_agent"]},
        ],
        tools=["OpenDART client", "official URL loader", "document indexer", "vLLM/Gemma", "JSON schema validation"],
        controls=["official_source_only", "source_traceability", "allowed_citation_labels_only", "fallback_on_invalid_json"],
        role_prompt=(
            "You are the Company Onboarding Agent, an AX delivery discovery specialist. "
            "Your responsibility is to create the traceable company context for the whole workflow. "
            "Use only official URLs, OpenDART data, uploaded files, or explicit user input. "
            "You may use an LLM only to structure company-specific candidate processes from source-grounded excerpts. "
            "Never invent internal operations, business units, or process facts that are not supported by the supplied evidence labels."
        ),
        task_instructions=[
            "Resolve the company identity, homepage, public profile, and analysis scope.",
            "Ingest official sources and preserve source URLs, source labels, and document metadata.",
            "Discover realistic AX candidate processes from official source excerpts using strict JSON output.",
            "Attach only allowed evidence labels to generated process candidates.",
            "Use deterministic fallback candidates when LLM discovery fails validation.",
        ],
        quality_checks=[
            "Reject non-official URLs unless explicitly allowed by the caller.",
            "Every generated process must be source-grounded or marked as fallback.",
            "LLM output must pass JSON schema and allowed citation-label validation.",
        ],
        output_contract=[
            "company_id, project_id, document_ids, and process_ids must be created or reused idempotently.",
            "company_profile and process discovery metadata must remain traceable to official source labels.",
        ],
        handoff_notes=["Pass company/project/document/process identifiers to Context & Evidence Agent."],
    ),
    AgentSpec(
        id="context_evidence_agent",
        name="Context & Evidence Agent",
        category="rag_and_evidence",
        purpose="DB에 저장된 분석 context를 로드하고, 업무별 RAG 근거와 citation source를 구성한다.",
        implementation="tool_based_rag_retrieval",
        managed_nodes=["load_project_data", "retrieve_context"],
        capabilities=[
            {"name": "project_context_loading", "node_role": "project, company, process, document, system 정보를 DB에서 로드", "nodes": ["load_project_data"]},
            {"name": "rag_evidence_retrieval", "node_role": "업무별 pgvector 검색, evidence item 생성, used_sources 구성", "nodes": ["retrieve_context"]},
        ],
        tools=["PostgreSQL", "pgvector retriever", "evidence collector"],
        controls=["traceable_chunk_metadata", "citation_label_preservation", "document_access_boundary"],
        role_prompt=(
            "You are the Context & Evidence Agent, the evidence librarian for the AX planner graph. "
            "Your role is to load project context and retrieve only traceable evidence for each candidate process. "
            "Do not analyze ROI, feasibility, or compliance. Do not upgrade confidence when evidence is missing. "
            "Your output is the evidence substrate used by all downstream expert Agents."
        ),
        task_instructions=[
            "Load project, company, departments, systems, business processes, and documents from the database.",
            "Retrieve process-specific context from pgvector and preserve chunk/document/source metadata.",
            "Build evidence_items and used_sources with stable citation labels.",
            "Deduplicate sources without losing source kind, URL, security level, or document linkage.",
            "Mark missing RAG evidence explicitly instead of silently assuming support.",
        ],
        quality_checks=[
            "Every evidence item must be traceable to document/chunk/source metadata.",
            "Confidential or restricted documents must preserve access-boundary metadata.",
            "Do not treat boilerplate or unrelated web text as process evidence.",
        ],
        output_contract=[
            "retrieved_contexts, evidence_items, and used_sources must be available to downstream nodes.",
            "Each source must preserve citation label, source kind, URL or upload reference, and document id where available.",
        ],
        handoff_notes=["Pass evidence state to diagnosis, governance, evaluation, and delivery Agents."],
    ),
    AgentSpec(
        id="process_diagnosis_agent",
        name="Process Diagnosis Agent",
        category="analysis",
        purpose="업무별 병목, 데이터 준비도, 자동화 보조 가능성을 진단한다.",
        implementation="rule_plus_rag_deterministic_scoring",
        managed_nodes=["process_analyzer", "data_readiness", "automation_feasibility"],
        capabilities=[
            {"name": "process_bottleneck_analysis", "node_role": "업무 문제, 대상 사용자, 현재 흐름, 문서 의존성, 근거 요약", "nodes": ["process_analyzer"]},
            {"name": "data_readiness_scoring", "node_role": "데이터 접근성, 문서 연결성, 접근권한 기반 readiness 분류", "nodes": ["data_readiness"]},
            {"name": "automation_feasibility_scoring", "node_role": "반복성, 기대효과, 구현 가능성, 위험도 기반 assistive automation 가능성 계산", "nodes": ["automation_feasibility"]},
        ],
        tools=["RAG context reader", "deterministic score calculator"],
        controls=["evidence_required_for_key_claims", "data_preparation_flag", "assistive_only_by_default"],
        role_prompt=(
            "You are the Process Diagnosis Agent, an operations-analysis expert for AX planning. "
            "Your responsibility is to diagnose how each candidate process works, whether the data is ready, "
            "and whether AI can safely assist the workflow. You must stay evidence-grounded and conservative. "
            "Do not create new process candidates and do not recommend autonomous execution authority."
        ),
        task_instructions=[
            "Analyze only business_processes already provided in the graph state.",
            "Summarize process problem, target user, current workflow, bottleneck, and evidence source.",
            "Classify data readiness using deterministic thresholds and document linkage.",
            "Estimate assistive automation feasibility from repeatability, expected effect, tech feasibility, and risk score.",
            "Use recommendation, retrieval, drafting, triage, monitoring, or review-support framing by default.",
        ],
        quality_checks=[
            "Do not mark readiness high when data_accessibility is below configured thresholds.",
            "Do not treat marketing slogans as internal workflow facts.",
            "Feasibility comments must explain the driver, not only repeat the numeric score.",
        ],
        output_contract=[
            "process_analysis, data_readiness, and automation_feasibility must be keyed by process_id.",
            "Each item must include enough rationale for priority ranking and report generation.",
        ],
        handoff_notes=["Pass diagnosis outputs to Business Case and Governance Agents."],
    ),
    AgentSpec(
        id="business_case_agent",
        name="Business Case Agent",
        category="calculation_and_prioritization",
        purpose="업무 후보의 비용 절감 가능성과 PoC 우선순위를 산정한다.",
        implementation="deterministic_calculation_and_weighted_ranking",
        managed_nodes=["roi_cost", "priority_ranking"],
        capabilities=[
            {"name": "roi_cost_calculation", "node_role": "현재 비용, 예상 비용, 절감률, PoC 비용 계산", "nodes": ["roi_cost"]},
            {"name": "candidate_priority_ranking", "node_role": "효과, 반복성, readiness, ROI, risk 기반 우선순위 산정", "nodes": ["priority_ranking"]},
        ],
        tools=["ROI calculator", "score calculator"],
        controls=["formula_traceability", "no_llm_financial_guessing", "bounded_score_weights"],
        role_prompt=(
            "You are the Business Case Agent, a deterministic prioritization expert. "
            "Your responsibility is to calculate comparable PoC economics and rank candidate Agents. "
            "You must not invent financial assumptions with an LLM. Treat ROI as a planning estimate, not an investment guarantee. "
            "Your ranking is a candidate recommendation that must still pass evaluator and human review controls."
        ),
        task_instructions=[
            "Calculate current cost, expected cost, saving amount, saving rate, PoC cost, and relative ROI with traceable formulas.",
            "Use automation_feasibility.expected_time_reduction_rate as the main savings driver.",
            "Combine diagnosis, readiness, ROI, and risk fields into a bounded weighted ranking.",
            "Keep blocked or evidence-insufficient candidates from being treated as final winners.",
            "Preserve score rationale for report and audit output.",
        ],
        quality_checks=[
            "Do not use LLM-generated financial assumptions.",
            "saving_rate and final_score must be numeric and bounded.",
            "Assumption-heavy calculations should be visible to downstream evaluation.",
        ],
        output_contract=[
            "roi_cost and priority_ranking must be generated with process_id references.",
            "ranking items must include final_score, saving_rate, status, rationale, risk flags, and review requirements.",
        ],
        handoff_notes=["Pass ranked candidates to Evaluation & Critic Agent."],
    ),
    AgentSpec(
        id="governance_compliance_agent",
        name="Governance & Compliance Agent",
        category="governance",
        purpose="보안, 개인정보, 기밀, 고영향 가능성, 금지 가능 사용을 점검한다.",
        implementation="policy_rule_engine_with_regulatory_mapping",
        managed_nodes=["risk_governance", "compliance_assessment"],
        capabilities=[
            {"name": "risk_signal_screening", "node_role": "업무명, 문제, workflow, 문서, RAG context에서 risk flag 탐지", "nodes": ["risk_governance"]},
            {"name": "regulatory_mapping", "node_role": "EU AI Act, Korea AI Basic Act proxy, privacy/security mapping 생성", "nodes": ["compliance_assessment"]},
        ],
        tools=["policy rule engine", "regulatory mapping rules"],
        controls=["prohibited_use_screening", "high_impact_screening", "human_oversight_required", "incident_logging"],
        human_review_required=True,
        regulatory_notes=[
            "Regulatory mapping is operational screening for PoC planning, not legal advice.",
            "Sensitive or high-impact signals must be escalated even if expected ROI is high.",
        ],
        role_prompt=(
            "You are the Governance & Compliance Agent, the safety and policy expert for AX candidate selection. "
            "Your job is to detect prohibited-use, high-impact, privacy, security, confidential-data, safety, employment, finance, "
            "healthcare, education, and legal/public-service risk signals. You must be conservative and escalate uncertain cases. "
            "Do not let high ROI downgrade governance obligations."
        ),
        task_instructions=[
            "Scan process names, target users, problems, workflows, documents, and RAG context for risk triggers.",
            "Assign risk flags, severity, human_review_required, and required controls.",
            "Map candidates to standard, sensitive_review, enhanced_review, or blocked compliance levels.",
            "Block prohibited-use candidates and require Human Review for sensitive or high-impact candidates.",
            "Summarize risk category and controls without exposing confidential source text.",
        ],
        quality_checks=[
            "Blocked candidates must not remain recommended.",
            "Enhanced or sensitive review candidates must require Human Review.",
            "Compliance level must not be lowered because of high ROI or high feasibility.",
        ],
        output_contract=[
            "risk_governance and compliance_assessment must be generated for ranking/evaluation/report.",
            "Each compliance item must include level, blocked flag, human review flag, required controls, and regulatory mappings.",
        ],
        handoff_notes=["Pass governance results to Evaluation & Critic and Delivery Orchestration Agents."],
    ),
    AgentSpec(
        id="evaluation_critic_agent",
        name="Evaluation & Critic Agent",
        category="evaluation",
        purpose="우선순위 결과의 근거 충분성, confidence, compliance alignment를 재검증하고 필요 시 replan을 수행한다.",
        implementation="deterministic_quality_gate_with_optional_llm_critic",
        managed_nodes=["agent_evaluator", "llm_critic", "agent_replan"],
        capabilities=[
            {"name": "deterministic_agent_evaluation", "node_role": "evidence coverage, data confidence, rationale coverage, compliance alignment 계산", "nodes": ["agent_evaluator"]},
            {"name": "llm_second_opinion", "node_role": "LLM 기반 보조 검토와 confidence calibration", "nodes": ["llm_critic"]},
            {"name": "bounded_replan", "node_role": "추가 근거가 유효할 때 제한된 replan loop 수행", "nodes": ["agent_replan"]},
        ],
        tools=["evidence coverage scorer", "LLM critic", "quality gate", "replan router"],
        controls=["no_recommendation_without_evidence", "compliance_alignment_check", "confidence_thresholding", "bounded_replan_loop"],
        human_review_required=True,
        role_prompt=(
            "You are the Evaluation & Critic Agent, the independent quality gate for the AX planner. "
            "Your responsibility is to challenge the priority ranking, verify evidence coverage, check compliance alignment, "
            "and calibrate confidence. Deterministic evaluation is the source of truth; LLM critique is only a second opinion. "
            "If evidence is weak, route to evidence_insufficient or bounded replan instead of approving."
        ),
        task_instructions=[
            "Evaluate each ranked candidate for evidence coverage, data confidence, rationale coverage, and risk uncertainty.",
            "Map blocked compliance to excluded and sensitive/enhanced review to Human Review.",
            "Use LLM critic only for structured second-opinion review and JSON-schema-compatible output.",
            "Trigger replan only when additional evidence collection is likely to improve a candidate decision.",
            "Keep replan loops bounded and auditable.",
        ],
        quality_checks=[
            "Zero or very weak evidence must not remain recommended.",
            "LLM critic failure must fall back to deterministic evaluation.",
            "Review gate must remain conservative even when status accuracy is high.",
        ],
        output_contract=[
            "agent_evaluation must include predicted_status, confidence_score, evidence metrics, issues, review flag, and replan flag.",
            "priority_ranking_after_evaluation must preserve candidate order while updating status/review flags where needed.",
        ],
        handoff_notes=["Pass evaluated candidates to Delivery Orchestration Agent."],
    ),
    AgentSpec(
        id="delivery_orchestration_agent",
        name="Delivery Orchestration Agent",
        category="supervisor_output",
        purpose="Human Review 이후 승인 후보를 PoC 계획과 보고서 산출물로 전환한다.",
        implementation="human_in_the_loop_delivery_supervisor",
        managed_nodes=["human_review", "poc_delivery_planner", "report_writer", "docx_generator"],
        capabilities=[
            {"name": "human_review_gate", "node_role": "approve/edit/reject 검토 기록 수집과 graph resume", "nodes": ["human_review"]},
            {"name": "poc_delivery_planning", "node_role": "승인 후보 기반 6주 PoC 계획, milestone, KPI 생성", "nodes": ["poc_delivery_planner"]},
            {"name": "report_generation", "node_role": "근거 기반 report_data 생성, LLM 문장화, citation validation", "nodes": ["report_writer"]},
            {"name": "docx_export", "node_role": "report_data를 DOCX 파일로 내보내기", "nodes": ["docx_generator"]},
        ],
        tools=["LangGraph interrupt", "report writer", "citation validator", "docx generator"],
        controls=["human_review_gate", "transparent_ai_disclosure", "citation_validation", "audit_trail"],
        human_review_required=True,
        role_prompt=(
            "You are the Delivery Orchestration Agent, the final AX delivery planning supervisor. "
            "Your responsibility is to convert evaluated and reviewed candidates into an actionable PoC plan and report. "
            "You must preserve the Human Review record, disclose AI-assisted generation, validate citations, and export a reviewable DOCX. "
            "Do not present unapproved or evidence-insufficient candidates as final PoC selections."
        ),
        task_instructions=[
            "Pause for Human Review or apply the provided review decision before final delivery outputs.",
            "Select an approved candidate and build a 6-week PoC plan with milestones, entry criteria, exit criteria, and KPIs.",
            "Generate report_data from deterministic base data and use LLM only for grounded paragraph drafting when available.",
            "Validate all report citations against used_sources or evidence_items.",
            "Export the final report to DOCX and preserve output path in state.",
        ],
        quality_checks=[
            "Do not generate final-status report without an approval record.",
            "Do not select excluded or evidence_insufficient candidates as the first PoC candidate.",
            "Report references must tie back to used_sources or evidence_items.",
        ],
        output_contract=[
            "human_review, poc_plan, report_data, and report_docx_path must be produced.",
            "report_data must include review status, AI-use disclosure, references, and citation validation results.",
        ],
        handoff_notes=["Return report_docx_path and workflow state to CLI/API caller."],
    ),
]


def get_agent_registry() -> list[dict[str, Any]]:
    return [item.to_dict() for item in AGENT_REGISTRY]


def get_agent_spec(agent_id: str) -> dict[str, Any] | None:
    for item in AGENT_REGISTRY:
        if item.id == agent_id:
            return item.to_dict()
    return None


def get_capability_for_node(agent_spec: dict[str, Any], node_name: str) -> dict[str, Any] | None:
    for capability in agent_spec.get("capabilities", []) or []:
        if node_name in capability.get("nodes", []):
            return dict(capability)
    return None


__all__ = [
    "AgentSpec",
    "AGENT_REGISTRY",
    "get_agent_registry",
    "get_agent_spec",
    "get_capability_for_node",
]
