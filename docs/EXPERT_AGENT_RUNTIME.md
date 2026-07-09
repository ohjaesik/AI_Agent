# Expert Agent Runtime Structure

This project uses an expert-agent structure instead of creating one Agent for every tool or graph node.

The runtime hierarchy is:

```text
Expert Agent
  └─ capability
      └─ LangGraph node
          ├─ candidate tools, max 3 per node
          ├─ selected tool / LLM / rule / RAG execution
          └─ post-tool Agent decision
```

## Why this structure

Tool-level Agents make the system noisy and difficult to explain. For example, `docx_generator`, `citation_validator`, and `score_calculator` are tools or execution steps, not independent decision-making Agents.

The system therefore uses expert Agents as responsibility, governance, prompt, tool-permission, tool-selection, post-decision, and audit units. Each expert Agent owns several graph nodes through named capabilities and can choose among up to three tool candidates per node.

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
- `tool_specs`
- `tools`
- `controls`
- `human_review_required`
- `regulatory_notes`
- `role_prompt`
- `task_instructions`
- `quality_checks`
- `output_contract`
- `handoff_notes`

`tool_specs` define the concrete tools the Agent can call, including description, input schema, output schema, purpose, and bound graph nodes. `get_tool_specs_for_node()` limits candidates to `MAX_TOOL_CANDIDATES_PER_NODE = 3`.

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

## Runtime tool calling and decisions

`app/agents/expert_executor.py` replaces direct graph node execution with an expert-Agent execution path.

```text
LangGraph node
  -> expert_executed_node(node_name, node_fn)
  -> resolve agent_id + capability from NODE_AGENT_BINDINGS
  -> load AgentSpec role_prompt/task_instructions/tool_specs
  -> load candidate tools for the node, max 3
  -> select one tool using state-aware rules
  -> call_agent_tool(agent_id, tool_name, payload, runner)
  -> run permission check
  -> execute the underlying node tool
  -> observe tool result
  -> apply post-tool Agent decision
  -> append agent_decisions, agent_tool_calls, agent_contracts, and audit_logs
```

`app/agents/tool_runtime.py` is the tool-calling gate. It validates the requested tool against `AgentSpec.tool_specs`, records `agent_tool_call_started`, runs the concrete node/tool function, records `agent_tool_call_succeeded`, and returns the observation to the expert executor.

The executor now records two decision phases per bound node:

```text
pre_tool_selection  : Agent chooses one tool from up to 3 candidates.
post_tool_observation: Agent observes the result and may pass through, add review metadata, request replan, downgrade weak-evidence candidates, or guard final delivery.
```

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

The selected tool is resolved from the Agent's candidate `tool_specs`.

Example `agent_contracts` item:

```json
{
  "node_name": "data_readiness",
  "agent_id": "process_diagnosis_agent",
  "agent_name": "Process Diagnosis Agent",
  "capability": "data_readiness_scoring",
  "candidate_tools": ["data_readiness_scorer", "data_gap_detector"],
  "selected_tool": "data_readiness_scorer",
  "post_decision": {
    "decision": "pass_through",
    "changed_output": false
  },
  "role_prompt": "You are the Process Diagnosis Agent, an operations-analysis expert for AX planning...",
  "task_instructions": ["..."]
}
```

Example `agent_tool_calls` item:

```json
{
  "node_name": "agent_evaluator",
  "agent_id": "evaluation_critic_agent",
  "capability": "deterministic_agent_evaluation",
  "candidate_tools": ["evidence_quality_gate", "review_status_calibrator", "evidence_replan_decider"],
  "tool_name": "evidence_replan_decider",
  "selection_reason": "evaluation must decide whether weak evidence should trigger bounded replan or human review",
  "observation": {
    "result_keys": ["agent_evaluation", "priority_ranking"]
  }
}
```

Example `agent_decisions` item:

```json
{
  "phase": "post_tool_observation",
  "node_name": "agent_evaluator",
  "agent_id": "evaluation_critic_agent",
  "selected_tool": "evidence_replan_decider",
  "decision": "request_replan_or_human_review",
  "changed_output": true,
  "additional_evidence_required_count": 3
}
```

The audit log keeps the compact execution trace, `agent_contracts` keeps the full prompt/contract metadata, `agent_tool_calls` keeps tool-call observations, and `agent_decisions` records the actual Agent-level decision that can change state output.

## State output

`python -m app.main --project-id <project_id> --auto-approve --verbose` saves the final workflow state to:

```text
outputs/workflow_state_real.json
```

The state should contain:

```json
{
  "agent_registry": [
    {"id": "company_onboarding_agent", "role_prompt": "...", "tool_specs": ["..."]},
    {"id": "context_evidence_agent", "role_prompt": "...", "tool_specs": ["..."]},
    {"id": "process_diagnosis_agent", "role_prompt": "...", "tool_specs": ["..."]},
    {"id": "business_case_agent", "role_prompt": "...", "tool_specs": ["..."]},
    {"id": "governance_compliance_agent", "role_prompt": "...", "tool_specs": ["..."]},
    {"id": "evaluation_critic_agent", "role_prompt": "...", "tool_specs": ["..."]},
    {"id": "delivery_orchestration_agent", "role_prompt": "...", "tool_specs": ["..."]}
  ],
  "agent_contracts": [
    {"node_name": "data_readiness", "candidate_tools": ["data_readiness_scorer", "data_gap_detector"], "selected_tool": "data_readiness_scorer"}
  ],
  "agent_tool_calls": [
    {"node_name": "data_readiness", "tool_name": "data_readiness_scorer"}
  ],
  "agent_decisions": [
    {"phase": "pre_tool_selection", "selected_tool": "data_readiness_scorer"},
    {"phase": "post_tool_observation", "decision": "pass_through"}
  ]
}
```

## Tests

```bash
pytest tests/test_agent_runtime.py tests/test_agent_evaluator.py
```
