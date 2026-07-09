# Expert Agent Runtime Structure

This project uses an expert-agent structure instead of creating one Agent for every tool or graph node.

The runtime hierarchy is:

```text
Expert Agent
  └─ capability
      └─ LangGraph node
          └─ tool / LLM / rule / RAG execution
```

## Why this structure

Tool-level Agents make the system noisy and difficult to explain. For example, `docx_generator`, `citation_validator`, and `score_calculator` are tools or execution steps, not independent decision-making Agents.

The system therefore uses expert Agents as responsibility, governance, and audit units. Each expert Agent owns several graph nodes through named capabilities.

## Single registry source

`app/agents/registry.py` is the single source of truth for Agent contracts.

There is no separate expert registry module. The public registry returns the 7 expert Agent contracts directly.

Each `AgentSpec` includes:

- `id`
- `name`
- `category`
- `purpose`
- `implementation`
- `managed_nodes`
- `capabilities`
- `tools`
- `controls`
- `human_review_required`
- `regulatory_notes`
- `role_prompt`
- `task_instructions`
- `quality_checks`
- `output_contract`
- `handoff_notes`

`role_prompt` defines what kind of expert the Agent is and what responsibility boundary it must follow. `task_instructions` define what the Agent should do when its managed nodes run.

## Expert Agents

| Expert Agent | Managed nodes | Responsibility |
|---|---|---|
| `company_onboarding_agent` | `company_profile_agent`, `source_ingestion_agent`, `process_discovery_agent` | Company profile, official source ingestion, initial process discovery |
| `context_evidence_agent` | `load_project_data`, `retrieve_context` | DB context loading and RAG evidence retrieval |
| `process_diagnosis_agent` | `process_analyzer`, `data_readiness`, `automation_feasibility` | Process bottleneck, data readiness, and automation feasibility diagnosis |
| `business_case_agent` | `roi_cost`, `priority_ranking` | ROI calculation and candidate prioritization |
| `governance_compliance_agent` | `risk_governance`, `compliance_assessment` | Risk screening and regulatory mapping |
| `evaluation_critic_agent` | `agent_evaluator`, `llm_critic`, `agent_replan` | Evidence quality gate, LLM second opinion, bounded replan |
| `delivery_orchestration_agent` | `human_review`, `poc_delivery_planner`, `report_writer`, `docx_generator` | Human review, PoC planning, report generation, DOCX export |

## Runtime contract binding

`app/agents/runtime.py` maps graph nodes to expert Agents through `NODE_AGENT_BINDINGS`.

Each binding includes:

```json
{
  "agent_id": "process_diagnosis_agent",
  "capability": "data_readiness_scoring",
  "node_role": "데이터 접근성, 문서 연결성, 접근권한 기반 readiness 분류"
}
```

At graph runtime, `with_agent_contract()` wraps each LangGraph node and appends an `agent_contracts` item to the state.

Example:

```json
{
  "node_name": "data_readiness",
  "agent_id": "process_diagnosis_agent",
  "agent_name": "Process Diagnosis Agent",
  "capability": "data_readiness_scoring",
  "node_role": "데이터 접근성, 문서 연결성, 접근권한 기반 readiness 분류",
  "implementation": "rule_plus_rag_deterministic_scoring",
  "role_prompt": "You are the Process Diagnosis Agent, an operations-analysis expert for AX planning...",
  "task_instructions": [
    "Analyze only business_processes already provided in the graph state.",
    "Classify data readiness using deterministic thresholds and document linkage."
  ],
  "managed_nodes": [
    "process_analyzer",
    "data_readiness",
    "automation_feasibility"
  ],
  "contract_found": true
}
```

The wrapper also appends an audit log entry with status `agent_contract_bound`. The audit log keeps the compact execution trace, while `agent_contracts` keeps the full prompt/contract metadata.

## State output

`python -m app.main --project-id <project_id> --auto-approve --verbose` saves the final workflow state to:

```text
outputs/workflow_state_real.json
```

The state should contain:

```json
{
  "agent_registry": [
    {"id": "company_onboarding_agent", "role_prompt": "..."},
    {"id": "context_evidence_agent", "role_prompt": "..."},
    {"id": "process_diagnosis_agent", "role_prompt": "..."},
    {"id": "business_case_agent", "role_prompt": "..."},
    {"id": "governance_compliance_agent", "role_prompt": "..."},
    {"id": "evaluation_critic_agent", "role_prompt": "..."},
    {"id": "delivery_orchestration_agent", "role_prompt": "..."}
  ],
  "agent_contracts": [
    {
      "node_name": "data_readiness",
      "agent_id": "process_diagnosis_agent",
      "capability": "data_readiness_scoring",
      "role_prompt": "...",
      "task_instructions": ["..."]
    }
  ]
}
```

## Tests

```bash
pytest tests/test_agent_runtime_contract.py tests/test_expert_agent_registry.py
```
