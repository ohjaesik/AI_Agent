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

`app/agents/expert_registry.py` defines the expert Agent contracts.

Each `ExpertAgentSpec` includes:

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
- `quality_checks`
- `output_contract`
- `handoff_notes`

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
  "managed_nodes": [
    "process_analyzer",
    "data_readiness",
    "automation_feasibility"
  ],
  "contract_found": true
}
```

The wrapper also appends an audit log entry with status `agent_contract_bound`.

## Public registry compatibility

`app/agents/registry.py` is kept as a compatibility module. It now returns the expert-level registry.

```python
from app.agents.registry import get_agent_registry, get_agent_spec

registry = get_agent_registry()
spec = get_agent_spec("process_diagnosis_agent")
```

This prevents old imports from returning the obsolete node/tool-level Agent catalog.

## State output

`python -m app.main --project-id <project_id> --auto-approve --verbose` saves the final workflow state to:

```text
outputs/workflow_state_real.json
```

The state should contain:

```json
{
  "agent_registry": [
    {"id": "company_onboarding_agent"},
    {"id": "context_evidence_agent"},
    {"id": "process_diagnosis_agent"},
    {"id": "business_case_agent"},
    {"id": "governance_compliance_agent"},
    {"id": "evaluation_critic_agent"},
    {"id": "delivery_orchestration_agent"}
  ],
  "agent_contracts": [
    {
      "node_name": "data_readiness",
      "agent_id": "process_diagnosis_agent",
      "capability": "data_readiness_scoring"
    }
  ]
}
```

## Tests

```bash
pytest tests/test_agent_runtime_contract.py tests/test_expert_agent_registry.py
```
