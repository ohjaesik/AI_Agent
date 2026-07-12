# app/agents/registry.py

"""시스템에 등록된 Expert Agent와 tool specification을 정의한다.

각 Agent가 어떤 node를 관리하고 어떤 tool을 사용할 수 있는지, 역할 prompt와
품질 기준, output contract가 무엇인지 선언하는 카탈로그다. runtime permission과
Supervisor prompt는 이 registry를 기준으로 만들어진다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.agents.tool_names import normalize_tool_name

MAX_TOOL_CANDIDATES_PER_NODE = 5

STATE_INPUT_SCHEMA = {
    "type": "object",
    "required": ["state"],
    "properties": {
        "state": {"type": "object", "description": "Current LangGraph state snapshot."},
        "agent_decision": {"type": "object", "description": "Pre-tool decision made by the expert Agent."},
    },
}

NODE_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "audit_logs": {"type": "array"},
        "errors": {"type": "array"},
        "agent_decisions": {"type": "array"},
    },
    "additionalProperties": True,
}


def tool_spec(name: str, description: str, nodes: list[str], purpose: str = "execute") -> dict[str, Any]:
    """Agent registry에 넣을 tool 계약서를 공통 schema와 함께 만든다."""
    return {
        "name": name,
        "description": description,
        "nodes": nodes,
        "purpose": purpose,
        "input_schema": STATE_INPUT_SCHEMA,
        "output_schema": NODE_OUTPUT_SCHEMA,
    }


@dataclass(frozen=True)
class AgentSpec:
    """Expert Agent 하나의 역할, 담당 node, tool, 품질 기준을 담는 registry 항목이다."""
    id: str
    name: str
    category: str
    purpose: str
    implementation: str
    managed_nodes: list[str]
    capabilities: list[dict[str, Any]]
    tool_specs: list[dict[str, Any]] = field(default_factory=list)
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
        """dataclass/value object를 JSON 직렬화 가능한 dict로 변환한다."""
        data = asdict(self)
        tool_names = [item.get("name") for item in self.tool_specs if item.get("name")]
        data["tools"] = sorted(set([*self.tools, *tool_names]))
        return data


AGENT_REGISTRY: list[AgentSpec] = [
    AgentSpec(
        id="company_onboarding_agent",
        name="Company Onboarding Agent",
        category="input_and_context",
        purpose="회사명, 공식 URL, OpenDART 정보를 기반으로 분석 대상 기업과 초기 업무 후보를 구성한다.",
        implementation="multi_tool_supervisor_with_llm_discovery",
        managed_nodes=["company_profile_agent", "source_ingestion_agent", "process_discovery_agent"],
        capabilities=[
            {"name": "company_profile_resolution", "node_role": "회사 식별, OpenDART 조회, company profile 생성/갱신", "nodes": ["company_profile_agent"]},
            {"name": "official_source_ingestion", "node_role": "공식 URL과 공시 자료 수집, 문서 저장, RAG 색인 준비", "nodes": ["source_ingestion_agent"]},
            {"name": "process_candidate_discovery", "node_role": "공식자료 기반 AX 후보 업무 생성과 evidence label 연결", "nodes": ["process_discovery_agent"]},
        ],
        tool_specs=[
            tool_spec("company_profile_loader", "Resolve company identity, OpenDART overview, and project bootstrap context.", ["company_profile_agent"]),
            tool_spec("profile_evidence_validator", "Check whether company profile fields are source-grounded before handoff.", ["company_profile_agent"], "validate"),
            tool_spec("official_source_ingestor", "Fetch official URLs and public filings and persist source documents.", ["source_ingestion_agent"]),
            tool_spec("source_quality_filter", "Reject weak or non-official source candidates before indexing.", ["source_ingestion_agent"], "validate"),
            tool_spec("process_discovery_llm", "Generate source-grounded AX candidate processes with JSON validation and fallback.", ["process_discovery_agent"]),
            tool_spec("discovery_fallback_planner", "Create conservative fallback process candidates when LLM discovery is weak.", ["process_discovery_agent"], "fallback"),
        ],
        tools=["OpenDART client", "official URL loader", "document indexer", "vLLM/Gemma", "JSON schema validation"],
        controls=["official_source_only", "source_traceability", "allowed_citation_labels_only", "fallback_on_invalid_json"],
        role_prompt=(
            "You are the Company Onboarding Agent, an AX delivery discovery specialist. Your responsibility is to create the traceable company context for the whole workflow. "
            "Use only official URLs, OpenDART data, uploaded files, or explicit user input. You may use an LLM only to structure company-specific candidate processes from source-grounded excerpts. "
            "Never invent internal operations, business units, or process facts that are not supported by supplied evidence labels."
        ),
        task_instructions=[
            "Resolve company identity and analysis scope.",
            "Ingest official sources with source labels and metadata.",
            "Discover realistic AX candidate processes from official source excerpts.",
            "Use fallback candidates only when LLM discovery is invalid or too weak.",
        ],
        quality_checks=["Reject non-official URLs unless explicitly allowed.", "Generated processes must be source-grounded or marked fallback."],
        output_contract=["company_id, project_id, document_ids, and process_ids must be created or reused idempotently."],
        handoff_notes=["Pass company/project/document/process identifiers to Context & Evidence Agent."],
    ),
    AgentSpec(
        id="context_evidence_agent",
        name="Context & Evidence Agent",
        category="rag_and_evidence",
        purpose="DB에 저장된 분석 context를 로드하고, 업무별 RAG 근거와 citation source를 구성한다.",
        implementation="multi_tool_rag_retrieval_and_evidence_gate",
        managed_nodes=["load_project_data", "retrieve_context"],
        capabilities=[
            {"name": "project_context_loading", "node_role": "project, company, process, document, system 정보를 DB에서 로드", "nodes": ["load_project_data"]},
            {"name": "rag_evidence_retrieval", "node_role": "업무별 pgvector 검색, evidence item 생성, used_sources 구성", "nodes": ["retrieve_context"]},
        ],
        tool_specs=[
            tool_spec("project_context_loader", "Load project, company, process, system, and document state from the database.", ["load_project_data"]),
            tool_spec("context_completeness_checker", "Check whether required project context is missing before analysis.", ["load_project_data"], "validate"),
            tool_spec("project_scope_validator", "Validate project/company alignment before downstream Agents rely on the loaded context.", ["load_project_data"], "validate"),
            tool_spec("document_access_policy_checker", "Check whether document security levels and user role boundaries are visible in context.", ["load_project_data"], "validate"),
            tool_spec("rag_retriever", "Retrieve process-specific evidence chunks and citation sources from pgvector.", ["retrieve_context"]),
            tool_spec("evidence_gap_detector", "Detect candidate processes with missing or weak evidence coverage.", ["retrieve_context"], "diagnose"),
            tool_spec("source_deduplicator", "Deduplicate citation sources while preserving source metadata.", ["retrieve_context"], "normalize"),
            tool_spec("context_requery_planner", "Plan follow-up retrieval terms when the first RAG pass is weak.", ["retrieve_context"], "plan"),
            tool_spec("source_lineage_inspector", "Inspect whether evidence items preserve source URL, document, and citation labels.", ["retrieve_context"], "validate"),
        ],
        tools=["PostgreSQL", "pgvector retriever", "evidence collector"],
        controls=["traceable_chunk_metadata", "citation_label_preservation", "document_access_boundary"],
        role_prompt=(
            "You are the Context & Evidence Agent, the evidence librarian for the AX planner graph. Your role is to load project context and retrieve only traceable evidence for each candidate process. "
            "Do not analyze ROI, feasibility, or compliance. Do not upgrade confidence when evidence is missing. Your output is the evidence substrate used by all downstream expert Agents."
        ),
        task_instructions=["Load project context from DB.", "Retrieve process-specific evidence.", "Mark missing RAG evidence explicitly."],
        quality_checks=["Every evidence item must be traceable.", "Do not treat unrelated web text as process evidence."],
        output_contract=["retrieved_contexts, evidence_items, and used_sources must be available to downstream nodes."],
        handoff_notes=["Pass evidence state to diagnosis, governance, evaluation, and delivery Agents."],
    ),
    AgentSpec(
        id="process_diagnosis_agent",
        name="Process Diagnosis Agent",
        category="analysis",
        purpose="업무별 병목, 데이터 준비도, 자동화 보조 가능성을 진단한다.",
        implementation="multi_tool_diagnostic_scoring",
        managed_nodes=["process_analyzer", "data_readiness", "automation_feasibility"],
        capabilities=[
            {"name": "process_bottleneck_analysis", "node_role": "업무 문제, 대상 사용자, 현재 흐름, 문서 의존성, 근거 요약", "nodes": ["process_analyzer"]},
            {"name": "data_readiness_scoring", "node_role": "데이터 접근성, 문서 연결성, 접근권한 기반 readiness 분류", "nodes": ["data_readiness"]},
            {"name": "automation_feasibility_scoring", "node_role": "반복성, 기대효과, 구현 가능성, 위험도 기반 assistive automation 가능성 계산", "nodes": ["automation_feasibility"]},
        ],
        tool_specs=[
            tool_spec("process_analyzer_tool", "Analyze process bottlenecks, target users, current flow, and evidence summary.", ["process_analyzer"]),
            tool_spec("process_evidence_checker", "Check whether process claims are supported by retrieved evidence.", ["process_analyzer"], "validate"),
            tool_spec("process_assumption_tracer", "Trace which process claims rely on DB fields versus RAG evidence.", ["process_analyzer"], "diagnose"),
            tool_spec("process_cluster_suggester", "Group similar candidate processes so downstream ranking can avoid duplicate PoCs.", ["process_analyzer"], "normalize"),
            tool_spec("data_readiness_scorer", "Score data accessibility, document linkage, and preparation requirements.", ["data_readiness"]),
            tool_spec("data_gap_detector", "Detect missing system, document, or access prerequisites before scoring high readiness.", ["data_readiness"], "diagnose"),
            tool_spec("automation_feasibility_scorer", "Score assistive automation fit from repeatability, effect, feasibility, and risk.", ["automation_feasibility"]),
            tool_spec("automation_risk_filter", "Downgrade automation fit when autonomous execution or high-risk use is implied.", ["automation_feasibility"], "validate"),
            tool_spec("automation_scope_guard", "Keep automation recommendations assistive unless explicit authority and controls exist.", ["automation_feasibility"], "guard"),
            tool_spec("workflow_exception_detector", "Identify process edge cases that require human fallback paths.", ["automation_feasibility"], "diagnose"),
        ],
        tools=["RAG context reader", "deterministic score calculator"],
        controls=["evidence_required_for_key_claims", "data_preparation_flag", "assistive_only_by_default"],
        role_prompt=(
            "You are the Process Diagnosis Agent, an operations-analysis expert for AX planning. Your responsibility is to diagnose how each candidate process works, whether the data is ready, and whether AI can safely assist the workflow. "
            "Stay evidence-grounded and conservative. Do not create new process candidates and do not recommend autonomous execution authority."
        ),
        task_instructions=["Analyze only provided business_processes.", "Classify readiness with deterministic thresholds.", "Use assistive automation framing by default."],
        quality_checks=["Do not mark readiness high when data accessibility is weak.", "Feasibility comments must explain the driver."],
        output_contract=["process_analysis, data_readiness, and automation_feasibility must be keyed by process_id."],
        handoff_notes=["Pass diagnosis outputs to Business Case and Governance Agents."],
    ),
    AgentSpec(
        id="business_case_agent",
        name="Business Case Agent",
        category="calculation_and_prioritization",
        purpose="업무 후보의 비용 절감 가능성과 PoC 우선순위를 산정한다.",
        implementation="multi_tool_business_case_and_status_calibration",
        managed_nodes=["roi_cost", "priority_ranking"],
        capabilities=[
            {"name": "roi_cost_calculation", "node_role": "현재 비용, 예상 비용, 절감률, PoC 비용 계산", "nodes": ["roi_cost"]},
            {"name": "candidate_priority_ranking", "node_role": "효과, 반복성, readiness, ROI, risk 기반 우선순위 산정", "nodes": ["priority_ranking"]},
        ],
        tool_specs=[
            tool_spec("roi_calculator", "Calculate baseline cost, expected savings, saving rate, and PoC cost estimates.", ["roi_cost"]),
            tool_spec("roi_assumption_checker", "Flag assumption-heavy ROI estimates before ranking.", ["roi_cost"], "validate"),
            tool_spec("roi_sensitivity_analyzer", "Check how ranking would change when weekly hours, cost, or saving assumptions shift.", ["roi_cost"], "analyze"),
            tool_spec("priority_ranker", "Rank candidates using deterministic weighted scores and governance-aware status.", ["priority_ranking"]),
            tool_spec("ranking_policy_reviewer", "Review ranking against governance, evidence, and human-review policies.", ["priority_ranking"], "review"),
            tool_spec("candidate_status_calibrator", "Adjust candidate status when evidence or compliance signals conflict with ranking score.", ["priority_ranking"], "calibrate"),
            tool_spec("portfolio_balance_checker", "Check whether the top PoC list over-concentrates in one department or risk type.", ["priority_ranking"], "validate"),
            tool_spec("cost_efficiency_reviewer", "Review whether high-score candidates remain cost-efficient after risk and evidence penalties.", ["priority_ranking"], "review"),
        ],
        tools=["ROI calculator", "score calculator"],
        controls=["formula_traceability", "no_llm_financial_guessing", "bounded_score_weights"],
        role_prompt=(
            "You are the Business Case Agent, a deterministic prioritization expert. Your responsibility is to calculate comparable PoC economics and rank candidate Agents. "
            "Do not invent financial assumptions with an LLM. Treat ROI as a planning estimate, not an investment guarantee. Your ranking must still pass evaluator and human review controls."
        ),
        task_instructions=["Calculate traceable ROI.", "Combine diagnosis, readiness, ROI, and risk into bounded ranking.", "Do not let high ROI override governance or evidence gaps."],
        quality_checks=["Do not use LLM-generated financial assumptions.", "saving_rate and final_score must be bounded."],
        output_contract=["roi_cost and priority_ranking must be generated with process_id references and decision rationale."],
        handoff_notes=["Pass ranked candidates to Evaluation & Critic Agent."],
    ),
    AgentSpec(
        id="governance_compliance_agent",
        name="Governance & Compliance Agent",
        category="governance",
        purpose="보안, 개인정보, 기밀, 고영향 가능성, 금지 가능 사용을 점검한다.",
        implementation="multi_tool_policy_screening_and_compliance_mapping",
        managed_nodes=["risk_governance", "compliance_assessment"],
        capabilities=[
            {"name": "risk_signal_screening", "node_role": "업무명, 문제, workflow, 문서, RAG context에서 risk flag 탐지", "nodes": ["risk_governance"]},
            {"name": "regulatory_mapping", "node_role": "EU AI Act, Korea AI Basic Act proxy, privacy/security mapping 생성", "nodes": ["compliance_assessment"]},
        ],
        tool_specs=[
            tool_spec("risk_rule_engine", "Detect privacy, security, high-impact, sensitive, and prohibited-use risk signals.", ["risk_governance"]),
            tool_spec("sensitive_use_escalator", "Escalate uncertain sensitive-use signals to human review.", ["risk_governance"], "escalate"),
            tool_spec("risk_false_positive_checker", "Review whether broad risk keywords are creating unnecessary human approval gates.", ["risk_governance"], "review"),
            tool_spec("approval_gate_minimizer", "Keep only mandatory approval gates when controls and evidence are sufficient.", ["risk_governance"], "calibrate"),
            tool_spec("compliance_mapper", "Map candidates to compliance levels, controls, and review requirements.", ["compliance_assessment"]),
            tool_spec("human_review_policy_mapper", "Map sensitive/enhanced review cases to concrete human oversight controls.", ["compliance_assessment"], "review"),
            tool_spec("control_evidence_checker", "Check whether required controls are backed by evidence or remain assumptions.", ["compliance_assessment"], "validate"),
            tool_spec("legal_review_boundary_marker", "Mark which compliance findings are technical screening versus legal advice.", ["compliance_assessment"], "guard"),
        ],
        tools=["policy rule engine", "regulatory mapping rules"],
        controls=["prohibited_use_screening", "high_impact_screening", "human_oversight_required", "incident_logging"],
        human_review_required=True,
        regulatory_notes=["Regulatory mapping is operational screening for PoC planning, not legal advice."],
        role_prompt=(
            "You are the Governance & Compliance Agent, the safety and policy expert for AX candidate selection. Your job is to detect prohibited-use, high-impact, privacy, security, confidential-data, safety, employment, finance, healthcare, education, and legal/public-service risk signals. "
            "Be conservative and escalate uncertain cases. Do not let high ROI downgrade governance obligations."
        ),
        task_instructions=["Scan process context for risk triggers.", "Assign risk flags and required controls.", "Block prohibited-use candidates and require Human Review for sensitive or high-impact candidates."],
        quality_checks=["Blocked candidates must not remain recommended.", "Compliance level must not be lowered because of high ROI."],
        output_contract=["risk_governance and compliance_assessment must include level, blocked flag, human review flag, and controls."],
        handoff_notes=["Pass governance results to Evaluation & Critic and Delivery Orchestration Agents."],
    ),
    AgentSpec(
        id="evaluation_critic_agent",
        name="Evaluation & Critic Agent",
        category="evaluation",
        purpose="우선순위 결과의 근거 충분성, confidence, compliance alignment를 재검증하고 필요 시 replan을 수행한다.",
        implementation="multi_tool_quality_gate_with_post_decision_calibration",
        managed_nodes=["agent_evaluator", "llm_critic", "agent_replan"],
        capabilities=[
            {"name": "deterministic_agent_evaluation", "node_role": "evidence coverage, data confidence, rationale coverage, compliance alignment 계산", "nodes": ["agent_evaluator"]},
            {"name": "llm_second_opinion", "node_role": "LLM 기반 보조 검토와 confidence calibration", "nodes": ["llm_critic"]},
            {"name": "bounded_replan", "node_role": "추가 근거가 유효할 때 제한된 replan loop 수행", "nodes": ["agent_replan"]},
        ],
        tool_specs=[
            tool_spec("evidence_quality_gate", "Evaluate evidence coverage, data confidence, rationale coverage, and compliance alignment.", ["agent_evaluator"]),
            tool_spec("review_status_calibrator", "Downgrade or hold candidates when evaluation conflicts with ranking status.", ["agent_evaluator"], "calibrate"),
            tool_spec("evidence_replan_decider", "Decide whether weak-evidence candidates should route to bounded replan.", ["agent_evaluator"], "route"),
            tool_spec("evaluation_outlier_detector", "Find candidates whose confidence, evidence, or risk signals conflict with their rank.", ["agent_evaluator"], "diagnose"),
            tool_spec("approval_need_minimizer", "Separate true human-approval cases from cases that only need automated evidence refresh.", ["agent_evaluator"], "calibrate"),
            tool_spec("llm_critic", "Use an LLM second opinion to calibrate candidate recommendation status.", ["llm_critic"]),
            tool_spec("critic_replan_decider", "Convert LLM review findings into replan or human-review routing hints.", ["llm_critic"], "route"),
            tool_spec("critic_status_calibrator", "Apply conservative status adjustments from LLM critique observations.", ["llm_critic"], "calibrate"),
            tool_spec("critic_adversarial_questioner", "Ask adversarial review questions before accepting top-ranked candidates.", ["llm_critic"], "review"),
            tool_spec("critic_confidence_floor_checker", "Prevent low-confidence candidates from being presented as final recommendations.", ["llm_critic"], "guard"),
            tool_spec("replan_router", "Run bounded evidence re-query and route back to retrieval or human review.", ["agent_replan"]),
            tool_spec("replan_productivity_checker", "Stop replan loops when source collection is unproductive.", ["agent_replan"], "validate"),
            tool_spec("replan_source_selector", "Select official-domain, public-search, or human-upload source paths for evidence gaps.", ["agent_replan"], "plan"),
            tool_spec("replan_stop_loss_guard", "Avoid repeated low-value evidence searches and escalate only when needed.", ["agent_replan"], "guard"),
        ],
        tools=["LLM critic", "quality gate", "evidence coverage scorer", "replan router"],
        controls=["no_recommendation_without_evidence", "compliance_alignment_check", "confidence_thresholding", "bounded_replan_loop"],
        human_review_required=True,
        role_prompt=(
            "You are the Evaluation & Critic Agent, the independent quality gate for the AX planner. Your responsibility is to challenge the priority ranking, verify evidence coverage, check compliance alignment, and calibrate confidence. "
            "Deterministic evaluation is the source of truth; LLM critique is a second opinion. If evidence is weak, route to evidence_insufficient or bounded replan instead of approving."
        ),
        task_instructions=["Evaluate every ranked candidate.", "Map blocked compliance to excluded.", "Trigger replan or conservative human review when evidence is weak.", "Keep replan loops bounded and auditable."],
        quality_checks=["Zero or very weak evidence must not remain recommended.", "LLM critic failure must fall back to deterministic evaluation."],
        output_contract=["agent_evaluation must include predicted_status, confidence_score, evidence metrics, issues, review flag, and replan flag."],
        handoff_notes=["Pass evaluated candidates to Delivery Orchestration Agent."],
    ),
    AgentSpec(
        id="delivery_orchestration_agent",
        name="Delivery Orchestration Agent",
        category="supervisor_output",
        purpose="Human Review 이후 승인 후보를 PoC 계획과 보고서 산출물로 전환한다.",
        implementation="multi_tool_human_in_the_loop_delivery_supervisor",
        managed_nodes=["human_review", "poc_delivery_planner", "report_writer", "docx_generator"],
        capabilities=[
            {"name": "human_review_gate", "node_role": "approve/edit/reject 검토 기록 수집과 graph resume", "nodes": ["human_review"]},
            {"name": "poc_delivery_planning", "node_role": "승인 후보 기반 6주 PoC 계획, milestone, KPI 생성", "nodes": ["poc_delivery_planner"]},
            {"name": "report_generation", "node_role": "근거 기반 report_data 생성, LLM 문장화, citation validation", "nodes": ["report_writer"]},
            {"name": "docx_export", "node_role": "report_data를 DOCX 파일로 내보내기", "nodes": ["docx_generator"]},
        ],
        tool_specs=[
            tool_spec("human_review_gate", "Pause or resume the graph with an explicit human review decision.", ["human_review"]),
            tool_spec("review_decision_validator", "Check whether review approval conflicts with evidence or compliance holds.", ["human_review"], "validate"),
            tool_spec("poc_planner", "Create a 6-week PoC plan with milestones, KPIs, and exit criteria.", ["poc_delivery_planner"]),
            tool_spec("poc_candidate_guard", "Hold PoC candidate selection when all candidates require evidence or governance follow-up.", ["poc_delivery_planner"], "guard"),
            tool_spec("poc_kpi_checker", "Check whether PoC KPIs are measurable from available systems and data.", ["poc_delivery_planner"], "validate"),
            tool_spec("report_writer", "Generate grounded report_data with AI disclosure and citation validation.", ["report_writer"]),
            tool_spec("citation_policy_reviewer", "Verify report claims against allowed sources and citation validation results.", ["report_writer"], "validate"),
            tool_spec("delivery_decision_summarizer", "Summarize Agent decisions, tool calls, and review gates for the report.", ["report_writer"], "summarize"),
            tool_spec("report_claim_gap_finder", "Find report sections that need more evidence or clearer caveats before DOCX export.", ["report_writer"], "validate"),
            tool_spec("report_reader_risk_checker", "Check whether wording overstates autonomous decisions or legal certainty.", ["report_writer"], "guard"),
            tool_spec("docx_exporter", "Export report_data to a reviewable DOCX artifact.", ["docx_generator"]),
            tool_spec("docx_artifact_checker", "Check whether the DOCX export path and metadata are present.", ["docx_generator"], "validate"),
            tool_spec("docx_delivery_readiness_checker", "Check whether the generated artifact has enough metadata for user handoff.", ["docx_generator"], "validate"),
            tool_spec("final_output_packager", "Prepare final report path, trace metadata, and decision summary for the caller.", ["docx_generator"], "summarize"),
        ],
        tools=["LangGraph interrupt", "citation validator", "docx generator"],
        controls=["human_review_gate", "transparent_ai_disclosure", "citation_validation", "audit_trail"],
        human_review_required=True,
        role_prompt=(
            "You are the Delivery Orchestration Agent, the final AX delivery planning supervisor. Your responsibility is to convert evaluated and reviewed candidates into an actionable PoC plan and report. "
            "Preserve Human Review records, disclose AI-assisted generation, validate citations, and export a reviewable DOCX. Do not present unapproved or evidence-insufficient candidates as final PoC selections."
        ),
        task_instructions=["Apply Human Review decision before final delivery.", "Build a 6-week PoC plan only from eligible candidates.", "Validate citations and export DOCX."],
        quality_checks=["Do not generate final-status report without approval record.", "Do not select excluded or evidence_insufficient candidates as first PoC candidate."],
        output_contract=["human_review, poc_plan, report_data, and report_docx_path must be produced with decision metadata."],
        handoff_notes=["Return report_docx_path and workflow state to CLI/API caller."],
    ),
]


def get_agent_registry() -> list[dict[str, Any]]:
    """Supervisor prompt와 permission report가 사용할 전체 Agent catalog를 반환한다."""
    return [item.to_dict() for item in AGENT_REGISTRY]


def get_agent_spec(agent_id: str) -> dict[str, Any] | None:
    """agent_id에 해당하는 Agent 계약서를 dict 형태로 조회한다."""
    for item in AGENT_REGISTRY:
        if item.id == agent_id:
            return item.to_dict()
    return None


def get_capability_for_node(agent_spec: dict[str, Any], node_name: str) -> dict[str, Any] | None:
    """Agent 계약서 안에서 특정 LangGraph node가 수행하는 capability를 찾는다."""
    for capability in agent_spec.get("capabilities", []) or []:
        if node_name in capability.get("nodes", []):
            return dict(capability)
    return None


def get_tool_specs_for_node(agent_id: str, node_name: str, max_tools: int = MAX_TOOL_CANDIDATES_PER_NODE) -> list[dict[str, Any]]:
    """특정 Agent/node 조합에서 Supervisor와 runtime이 노출해도 되는 tool 후보만 반환한다."""
    spec = get_agent_spec(agent_id)
    if not spec:
        return []
    matches = [dict(item) for item in spec.get("tool_specs", []) or [] if node_name in item.get("nodes", [])]
    return matches[:max_tools]


def get_tool_spec(agent_id: str, tool_name: str) -> dict[str, Any] | None:
    """tool 이름을 정규화해 Agent에게 허용된 단일 tool 계약서를 찾는다."""
    spec = get_agent_spec(agent_id)
    if not spec:
        return None
    normalized = normalize_tool_name(tool_name)
    for item in spec.get("tool_specs", []) or []:
        if normalize_tool_name(str(item.get("name") or "")) == normalized:
            return dict(item)
    return None


def get_tool_spec_for_node(agent_id: str, node_name: str) -> dict[str, Any] | None:
    """node 실행용 대표 tool spec 하나를 반환한다."""
    specs = get_tool_specs_for_node(agent_id, node_name, max_tools=1)
    return specs[0] if specs else None


__all__ = [
    "AgentSpec",
    "AGENT_REGISTRY",
    "MAX_TOOL_CANDIDATES_PER_NODE",
    "get_agent_registry",
    "get_agent_spec",
    "get_capability_for_node",
    "get_tool_spec",
    "get_tool_spec_for_node",
    "get_tool_specs_for_node",
]
