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
    role_prompt: str = ""
    task_instructions: list[str] = field(default_factory=list)
    output_contract: list[str] = field(default_factory=list)
    quality_checks: list[str] = field(default_factory=list)
    handoff_notes: list[str] = field(default_factory=list)

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
        human_review_required=False,
        regulatory_notes=[
            "투명성 확보를 위해 회사 프로필은 공식 출처 기반 필드와 출처 label로만 구성한다.",
            "웹 원문을 그대로 보고서에 노출하지 않고, RAG/출처 근거로만 보존한다.",
        ],
        role_prompt=(
            "You are the Company Profile Agent for an AX Delivery planning workflow. "
            "Your job is to convert a company name and official source URLs into a traceable company profile, "
            "analysis scope, and initial project context. Use only official or explicitly provided sources. "
            "Do not infer business units, products, or financial facts without source evidence. "
            "Prefer conservative, source-grounded summaries over broad market assumptions."
        ),
        task_instructions=[
            "Normalize the company name, aliases, homepage, industry, and analysis scope.",
            "Load official URLs and OpenDART data when available, preserving source URL and retrieval metadata.",
            "Extract only facts relevant to AX planning: business domains, service lines, departments, systems, and public strategic themes.",
            "Create or update the company profile and analysis project idempotently.",
            "Mark missing or weak fields as unknown instead of filling them with plausible guesses.",
        ],
        output_contract=[
            "company_profile must include company_id/name/industry/source_summary/source_labels where available.",
            "analysis_project must include project_id/company_id/status/scope.",
            "Every non-trivial field must be attributable to official_url, OpenDART, or user-provided input.",
        ],
        quality_checks=[
            "Reject non-official URLs unless the caller explicitly allows them.",
            "Check that every official URL is linked to a used_source entry.",
            "Do not expose raw scraped boilerplate as report-ready text.",
        ],
        handoff_notes=[
            "Pass company_profile and official source metadata to Source Ingestion Agent.",
            "Pass analysis_project id to downstream graph execution.",
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
        human_review_required=False,
        regulatory_notes=[
            "고위험·민감 문서가 포함될 수 있으므로 문서별 보안등급과 민감정보 여부를 저장한다.",
            "검색 결과는 citation label과 source metadata로 추적 가능해야 한다.",
        ],
        role_prompt=(
            "You are the Source Ingestion Agent. Your job is to turn official URLs and uploaded documents into "
            "clean, access-controlled, chunked, embedded evidence for RAG. Preserve provenance. "
            "Do not summarize away source boundaries. Do not index content without security level and source metadata."
        ),
        task_instructions=[
            "Load official URLs, PDFs, DOCX, TXT, and Markdown files using the appropriate loader.",
            "Normalize title, document type, department, process_id, security_level, allowed_roles, and source_url.",
            "Chunk documents with enough context for retrieval while keeping citation labels stable.",
            "Create embeddings and store chunks in pgvector with document_id, chunk_index, and source metadata.",
            "Detect sensitive indicators such as personal data, account data, confidential terms, HR, finance, and safety content.",
        ],
        output_contract=[
            "process_documents must identify document_id/title/source_url/security_level/allowed_roles.",
            "document_chunks must contain stable chunk metadata and citation labels.",
            "used_sources must deduplicate sources while preserving source_kind and URL.",
        ],
        quality_checks=[
            "Do not index empty, duplicated, or boilerplate-only chunks.",
            "Ensure confidential documents are not retrievable by roles outside allowed_roles.",
            "Ensure every chunk can be traced back to a document and source URL or uploaded file.",
        ],
        handoff_notes=[
            "Pass retrieved evidence metadata to Process Analysis, Risk Governance, and Report Writer.",
            "Expose missing-source warnings to Human Review when ingestion is incomplete.",
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
        human_review_required=False,
        regulatory_notes=[
            "생성형 AI 출력은 근거 label이 있는 후보만 저장하고, 실패 시 deterministic fallback을 사용한다.",
            "추천은 의사결정 확정이 아니라 Human Review 전 후보 생성으로 제한한다.",
        ],
        role_prompt=(
            "You are the Process Discovery Agent. You identify realistic AX/AI Agent candidate processes from official company materials. "
            "Generate candidates that could become planning, recommendation, RAG, monitoring, or workflow-assistive agents. "
            "Do not invent internal operations. Use only allowed evidence labels. Output strict JSON that can be stored directly."
        ),
        task_instructions=[
            "Read official source excerpts and identify repeated business themes, operating domains, systems, and customer/employee workflows.",
            "Generate company-specific business_process candidates rather than generic AI use cases.",
            "For each candidate, define process name, target user, current workflow, problem, candidate_agent_name, expected_effect, repeatability, document_dependency, decision_complexity, data_accessibility, tech_feasibility, and risk_score.",
            "Attach evidence_labels only from allowed_evidence_labels.",
            "Include discovery_metadata with suitability_rationale and score_rationale for every scored dimension.",
        ],
        output_contract=[
            "business_processes must be valid JSON records matching the DB/process schema.",
            "Each candidate must contain at least one allowed evidence label unless fallback mode is explicitly used.",
            "Each score must be 1-5 and accompanied by score_rationale.",
        ],
        quality_checks=[
            "Reject candidates that depend on unsupported company claims.",
            "Avoid autonomous decision-making agents for high-impact domains; describe them as assistive or review-based.",
            "Use fallback template when LLM output is malformed, citation labels are invalid, or required fields are missing.",
        ],
        handoff_notes=[
            "Pass business_processes to analysis nodes.",
            "Pass discovery_metadata to Automation Feasibility and Priority Ranking.",
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
        human_review_required=False,
        regulatory_notes=["업무 분석의 핵심 주장은 RAG 근거 또는 DB 필드에 연결한다."],
        role_prompt=(
            "You are the Process Analysis Agent. Your job is to translate each candidate business process into an operational diagnosis: "
            "who performs it, what friction exists, what documents or systems it depends on, and where an AI Agent can assist. "
            "Do not score ROI or compliance here. Focus on process facts and evidence-grounded bottlenecks."
        ),
        task_instructions=[
            "For each business_process, summarize target user, current workflow, bottleneck, decision points, and document dependency.",
            "Use retrieved_contexts first; if no context exists, explicitly mark evidence as RAG 근거 없음.",
            "Map each key claim to citation_label or DB field source.",
            "Separate actual process pain from proposed AI solution.",
            "Highlight process ambiguity that should be resolved during Human Review.",
        ],
        output_contract=[
            "process_analysis.items must include process_id, process_name, target_user, candidate_agent_name, problem, current_workflow, bottleneck, evidence, citation_label, and source.",
            "process_analysis.summary must include total_processes and counts for high-repeatability/high-document-dependency candidates.",
        ],
        quality_checks=[
            "Do not treat marketing slogans as internal workflow facts.",
            "Do not create new process candidates; analyze only provided business_processes.",
            "Flag missing evidence rather than silently upgrading confidence.",
        ],
        handoff_notes=[
            "Pass process_analysis to Priority Ranking and Report Writer.",
            "Expose weak evidence cases to Agent Evaluator through evidence fields.",
        ],
    ),
    AgentSpec(
        id="data_readiness_agent",
        name="Data Readiness Agent",
        category="analysis",
        purpose="데이터 접근성, 문서 품질, 권한 준비도를 평가한다.",
        implementation="deterministic_scoring",
        inputs=["business_processes", "documents"],
        outputs=["data_readiness"],
        tools=[],
        controls=["data_quality_check", "access_precondition_check", "data_preparation_flag"],
        human_review_required=False,
        regulatory_notes=["데이터 품질과 접근권한은 고위험 AI 의무의 데이터 거버넌스 요구와 연결되는 선행 통제다."],
        role_prompt=(
            "You are the Data Readiness Agent. Your job is to decide whether each process has enough accessible, structured, and governed data "
            "to support an AX PoC. You must be conservative: weak data means readiness is low or medium, not assumed ready."
        ),
        task_instructions=[
            "Inspect data_accessibility, linked documents, security_level, allowed_roles, and missing process evidence.",
            "Classify readiness as high, medium, or low using deterministic thresholds.",
            "Identify the minimum data preparation required before PoC: source collection, permission approval, data cleaning, labeling, or reindexing.",
            "Separate data availability from model feasibility; this agent only evaluates readiness of inputs and access.",
        ],
        output_contract=[
            "data_readiness.items must include process_id, process_name, data_accessibility, readiness_level, and comment.",
            "data_readiness.summary must include total_processes and low_readiness_count.",
        ],
        quality_checks=[
            "Do not mark readiness high when data_accessibility is below 4.",
            "Flag confidential or restricted documents as access preconditions.",
            "Do not assume uploaded documents are enough if they are not linked to the process.",
        ],
        handoff_notes=[
            "Pass readiness_level and data_accessibility to Agent Evaluator and Priority Ranking.",
            "Low readiness should reduce confidence or trigger evidence_insufficient status.",
        ],
    ),
    AgentSpec(
        id="automation_feasibility_agent",
        name="Automation Feasibility Agent",
        category="analysis",
        purpose="Agent 적용 가능성과 예상 시간 절감률을 판단한다.",
        implementation="deterministic_scoring_with_discovery_rationale",
        inputs=["business_processes", "discovery_metadata"],
        outputs=["automation_feasibility"],
        tools=[],
        controls=["assistive_only_by_default", "no_autonomous_execution", "rationale_logging"],
        human_review_required=False,
        regulatory_notes=["본 시스템은 업무 자동 실행이 아닌 판단 보조·추천형 Agent를 기본값으로 둔다."],
        role_prompt=(
            "You are the Automation Feasibility Agent. Your job is to estimate whether a process can be assisted by an AI Agent "
            "without giving the agent autonomous business authority. Treat all candidates as recommendation, retrieval, drafting, triage, monitoring, "
            "or review-support agents unless Human Review explicitly approves a stronger scope."
        ),
        task_instructions=[
            "Use expected_effect, repeatability, tech_feasibility, and risk_score to estimate expected_time_reduction_rate.",
            "Describe the feasible automation type, such as RAG Q&A, document drafting, exception triage, workflow checklist, or decision support.",
            "Log discovery_metadata.suitability_rationale and score_rationale where present.",
            "Reduce feasibility when the process needs real-time control, legal/financial final decisions, or sensitive employee/customer decisions.",
        ],
        output_contract=[
            "automation_feasibility.items must include process_id, process_name, candidate_agent_name, automation_type, tech_feasibility, expected_time_reduction_rate, and comment.",
            "automation_feasibility.summary must include total_processes and high_feasibility_count.",
        ],
        quality_checks=[
            "Never recommend direct equipment control, financial approval, hiring/firing, medical diagnosis, or legal final decision as autonomous execution.",
            "Expected time reduction must remain within configured deterministic bounds.",
            "Feasibility comments must explain the driver, not just repeat the score.",
        ],
        handoff_notes=[
            "Pass expected_time_reduction_rate to ROI & Cost Agent.",
            "Pass automation_type and feasibility comment to PoC Delivery Planner.",
        ],
    ),
    AgentSpec(
        id="roi_cost_agent",
        name="ROI & Cost Agent",
        category="calculation",
        purpose="현재 비용, 예상 비용, 절감액, 절감률을 계산한다.",
        implementation="deterministic_calculation",
        inputs=["business_processes", "automation_feasibility"],
        outputs=["roi_cost"],
        tools=[],
        controls=["formula_traceability", "no_llm_financial_guessing"],
        human_review_required=False,
        regulatory_notes=["재무성 추정은 고정 산식과 입력값 기반으로 계산하고 LLM 임의 추정을 금지한다."],
        role_prompt=(
            "You are the ROI & Cost Agent. Your job is to calculate comparable PoC economics using deterministic formulas. "
            "Do not invent financial figures. When inputs are missing, use documented defaults or mark the estimate as assumption-based. "
            "Your output supports prioritization, not investment approval."
        ),
        task_instructions=[
            "Calculate current cost, estimated post-agent cost, saving amount, saving_rate, PoC cost, and relative ROI using the configured formula.",
            "Use automation_feasibility.expected_time_reduction_rate as the main reduction driver.",
            "Keep formula inputs traceable to business_process fields or documented defaults.",
            "Flag estimates with weak input quality so they can be reviewed by a human owner.",
        ],
        output_contract=[
            "roi_cost.items must include process_id, process_name, current_cost, expected_cost, saving_amount, saving_rate, poc_cost, and calculation_basis where available.",
            "roi_cost.summary must include total_processes and aggregate saving/ROI indicators.",
        ],
        quality_checks=[
            "Do not use LLM-generated financial assumptions.",
            "Do not present ROI as guaranteed financial outcome.",
            "Check that saving_rate is numeric and bounded.",
        ],
        handoff_notes=[
            "Pass saving_rate and cost indicators to Priority Ranking and Report Writer.",
            "Assumption-heavy calculations should lower confidence in Agent Evaluator.",
        ],
    ),
    AgentSpec(
        id="risk_governance_agent",
        name="Risk & Governance Agent",
        category="governance",
        purpose="보안, 개인정보, 기밀, 고영향 가능성, Human Review 필요성을 판단한다.",
        implementation="policy_rule_engine",
        inputs=["business_processes", "retrieved_contexts", "documents"],
        outputs=["risk_governance", "compliance_assessment"],
        tools=[],
        controls=["prohibited_use_screening", "high_impact_screening", "human_oversight_required", "incident_logging"],
        human_review_required=True,
        regulatory_notes=[
            "금지영역 또는 고영향 가능성이 있으면 추천 자동 확정을 금지하고 Human Review로 전환한다.",
            "개인정보·기밀정보·채용·금융·의료·안전 관련 업무는 강화 통제를 적용한다.",
        ],
        role_prompt=(
            "You are the Risk & Governance Agent. Your job is to identify whether an AX candidate is standard, sensitive, high-impact, or blocked. "
            "You must protect the workflow from unsafe automation. Any process involving personal data, confidential data, employment, finance, healthcare, education, critical infrastructure, safety, legal decisions, or prohibited AI use must be escalated. "
            "This is a technical screening, not legal advice."
        ),
        task_instructions=[
            "Scan process names, problems, workflows, target users, documents, and retrieved contexts for sensitive and high-impact signals.",
            "Assign risk flags for personal/confidential data, restricted access, employment, finance, healthcare, safety, legal/public service, and prohibited-use indicators.",
            "Call compliance assessment logic to produce compliance_level, blocked, human_review_required, required_controls, regulatory_mappings, and regulatory_summary.",
            "Block candidates with prohibited-use triggers and route sensitive/high-impact candidates to Human Review.",
            "Record incident-style audit details for why a candidate was escalated or blocked.",
        ],
        output_contract=[
            "risk_governance.items must include process_id, risk_flags, severity, human_review_required, and rationale where available.",
            "compliance_assessment.items must include compliance_level, blocked, human_review_required, required_controls, regulatory_mappings, and regulatory_summary.",
            "summary must count blocked, enhanced_review, sensitive_review, and human_review_required candidates.",
        ],
        quality_checks=[
            "Do not allow a blocked candidate to remain recommended.",
            "Do not downgrade high-impact or sensitive contexts just because ROI is high.",
            "Do not expose confidential source text in final report; summarize risk category and control requirements instead.",
        ],
        handoff_notes=[
            "Pass compliance_assessment to Priority Ranking and Agent Evaluator.",
            "Pass regulatory mappings and required controls to Report Writer.",
        ],
    ),
    AgentSpec(
        id="agent_evaluator_agent",
        name="Agent Evaluator Agent",
        category="evaluation",
        purpose="우선순위 후보의 evidence coverage, data confidence, rationale coverage, compliance alignment, risk uncertainty를 재검증한다.",
        implementation="deterministic_quality_gate_with_optional_llm_critic",
        inputs=["priority_ranking", "evidence_items", "retrieved_contexts", "compliance_assessment"],
        outputs=["agent_evaluation", "priority_ranking_after_evaluation", "replan_request"],
        tools=["evidence coverage scorer", "LLM critic", "quality gate", "replan router"],
        controls=["no_recommendation_without_evidence", "compliance_alignment_check", "confidence_thresholding", "bounded_replan_loop"],
        human_review_required=True,
        regulatory_notes=[
            "근거가 부족하거나 compliance 정렬이 깨진 후보는 recommended 상태를 유지하지 않는다.",
            "반복 replan은 제한 횟수 내에서만 수행하고, 한계 도달 시 Human Review로 넘긴다.",
        ],
        role_prompt=(
            "You are the Agent Evaluator Agent. Your job is to challenge the Priority Ranking result before it reaches Human Review. "
            "Evaluate whether each recommended candidate is sufficiently supported by evidence, data readiness, score rationale, and compliance alignment. "
            "Downgrade unsafe or weakly supported candidates. Prefer human_review_required or evidence_insufficient over overconfident recommendations."
        ),
        task_instructions=[
            "Compute evidence_coverage, data_confidence, rationale_coverage, compliance_alignment, risk_uncertainty, and confidence_score.",
            "Reclassify status to excluded, evidence_insufficient, human_review_required, or recommended according to policy order.",
            "Mark requires_additional_evidence only when additional sources could materially improve the decision.",
            "Use LLM Critic as second opinion when enabled, but keep deterministic fallback as source of truth when LLM fails.",
            "Generate replan_request only within AGENT_REPLAN_MAX_ATTEMPTS and route to Human Review when the loop is capped or unproductive.",
        ],
        output_contract=[
            "agent_evaluation.items must include process_id, candidate_agent_name, predicted_status, confidence_score, evidence_coverage, data_confidence, rationale_coverage, risk_uncertainty, issues, requires_human_review, and requires_additional_evidence.",
            "agent_evaluation.summary must include evaluated_candidates, average_confidence_score, low_confidence_count, human_review_required_count, and additional_evidence_required_count.",
            "priority_ranking_after_evaluation must preserve candidate order while updating status/review flags where needed.",
        ],
        quality_checks=[
            "Blocked compliance must map to excluded.",
            "Enhanced or sensitive review must require Human Review.",
            "Zero or very weak evidence must map to evidence_insufficient instead of recommended.",
            "Review gate must remain conservative even when status accuracy is high.",
        ],
        handoff_notes=[
            "Pass evaluated ranking to LLM Critic and Human Review.",
            "Pass replan_request to Agent Replan Loop when additional evidence is still useful and allowed.",
        ],
    ),
    AgentSpec(
        id="priority_delivery_agent",
        name="Priority & Delivery Agent",
        category="supervisor_output",
        purpose="우선순위 산정, Human Review, PoC 계획, 보고서 생성을 지휘한다.",
        implementation="supervisor_with_human_in_the_loop",
        inputs=["process_analysis", "data_readiness", "automation_feasibility", "roi_cost", "risk_governance", "compliance_assessment", "agent_evaluation"],
        outputs=["priority_ranking", "human_review", "poc_plan", "report_data", "report_docx_path"],
        tools=["score calculator", "LangGraph interrupt", "report writer", "docx generator"],
        controls=["human_review_gate", "transparent_ai_disclosure", "citation_validation", "audit_trail"],
        human_review_required=True,
        regulatory_notes=[
            "최종 산출물은 AI 생성/보조 보고서임을 표시하고, Human Review 기록을 포함한다.",
            "PoC 착수는 추천 결과가 아니라 검토자 승인 기록을 기준으로 한다.",
        ],
        role_prompt=(
            "You are the Priority & Delivery Agent. Your job is to integrate all analysis results into an executive-ready AX PoC recommendation. "
            "You must not treat scoring as automatic approval. Use Human Review as the decision gate and produce a practical 6-week PoC plan for the safest, best-supported candidate."
        ),
        task_instructions=[
            "Combine process_analysis, data_readiness, automation_feasibility, roi_cost, risk_governance, compliance_assessment, and agent_evaluation.",
            "Rank candidates by expected effect, repeatability, data readiness, feasibility, ROI, evidence strength, and governance risk.",
            "Expose top candidates, status, rationale, confidence, risks, and required controls to Human Review.",
            "After approval, build a PoC plan with scope freeze, data/RAG readiness, prototype, user review/governance, and go/no-go milestones.",
            "Generate report_data and DOCX output with transparent AI-use disclosure, citations, review status, and references.",
        ],
        output_contract=[
            "priority_ranking must include ordered items with final_score, saving_rate, status, rationale, risk_flags, and review requirements.",
            "human_review must include decision, reviewer_name, comment, and optional edited_payload.",
            "poc_plan must include mvp_agent, milestones, entry_criteria, exit_criteria, and KPIs.",
            "report_data must include title, executive_summary, sections, references, status, and citation validation where available.",
        ],
        quality_checks=[
            "Do not select excluded or evidence_insufficient candidates as first PoC candidate.",
            "Do not hide Human Review requirements from the report.",
            "Do not generate final-status report without approval record.",
            "Ensure report references are tied to used_sources or evidence_items.",
        ],
        handoff_notes=[
            "Handoff final DOCX path to CLI/API response.",
            "Store audit trail and analysis results for future comparison across companies.",
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
