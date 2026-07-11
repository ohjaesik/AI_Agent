<!-- 파일 역할: Expert Agent runtime 계층, registry, tool permission, package 구조를 설명한다. -->

# Expert Agent Runtime Structure

This project uses an Agent-stage workflow instead of creating one Agent for every tool or bare graph node.

The runtime hierarchy is:

```text
AX Delivery Supervisor Agent
  └─ Expert Agent stage
      ├─ assigned internal nodes
      │   └─ assigned tools, max 3 per internal node
      ├─ Agent package artifact
      └─ Agent-to-Agent handoff
```

## Why this structure

Tool-level Agents make the system noisy and difficult to explain. For example, `docx_generator`, `citation_validator`, and `score_calculator` are tools or execution steps, not independent decision-making Agents.

The system therefore uses Expert Agents as responsibility, governance, prompt, tool-permission, post-decision, package, and handoff units. The top-level Supervisor delegates work to each Expert Agent stage, and each Expert Agent runs only its assigned internal nodes/tools.

## Single registry source

`app/agents/registry.py` is the single source of truth for Agent contracts.

There is no separate expert registry module. The public registry returns the 7 Expert Agent contracts directly.

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

`tool_specs` define the concrete tools the Agent can call, including description, input schema, output schema, purpose, and bound internal nodes. `get_tool_specs_for_node()` limits candidates to `MAX_TOOL_CANDIDATES_PER_NODE = 3`.

## Expert Agents

| Expert Agent | Internal nodes | Responsibility |
|---|---|---|
| `company_onboarding_agent` | `company_profile_agent`, `source_ingestion_agent`, `process_discovery_agent` | Company profile, official source ingestion, initial process discovery |
| `context_evidence_agent` | `load_project_data`, `retrieve_context` | DB context loading and RAG evidence retrieval |
| `process_diagnosis_agent` | `process_analyzer`, `data_readiness`, `automation_feasibility` | Process bottleneck, data readiness, and automation feasibility diagnosis |
| `governance_compliance_agent` | `risk_governance`, `compliance_assessment` | Risk screening and regulatory mapping |
| `business_case_agent` | `roi_cost`, `priority_ranking` | ROI calculation and candidate prioritization |
| `evaluation_critic_agent` | `agent_evaluator`, `llm_critic`, `agent_replan` | Evidence quality gate, LLM second opinion, bounded replan |
| `delivery_orchestration_agent` | `human_review`, `poc_delivery_planner`, `report_writer`, `docx_generator` | Human review, PoC planning, report generation, DOCX export |

## Agent-stage workflow

`app/graph/workflow.py` now groups the old node graph into Agent-stage nodes:

```text
context_evidence_agent
  -> process_diagnosis_agent
  -> business_case_agent
  -> evaluation_critic_agent
  -> delivery_orchestration_agent

context_evidence_agent
  -> governance_compliance_agent
  -> business_case_agent

evaluation_critic_agent
  -> agent_replan
  -> context_evidence_agent | delivery_orchestration_agent
```

Each Agent-stage node runs its assigned internal nodes in order. For example, `business_case_agent` runs `roi_cost` and then `priority_ranking`; `delivery_orchestration_agent` runs `human_review`, `poc_delivery_planner`, `report_writer`, and `docx_generator`.

## Internal tool calling and decisions

`app/agents/expert_executor.py` wraps each internal node execution with the owning Expert Agent's tool loop.

```text
Expert Agent stage
  -> internal node
  -> expert_executed_node(node_name, node_fn)
  -> resolve agent_id + capability from NODE_AGENT_BINDINGS
  -> load AgentSpec role_prompt/task_instructions/tool_specs
  -> run the assigned tool set for that internal node
  -> call_agent_tool(agent_id, tool_name, payload, runner)
  -> run permission check
  -> execute/observe tool result
  -> apply post-tool Agent decision
  -> append agent_decisions, agent_tool_calls, agent_contracts, and audit_logs
```

`app/agents/tool_runtime.py` is the tool-calling gate. It validates the requested tool against `AgentSpec.tool_specs`, records `agent_tool_call_started`, runs the concrete node/tool function, records `agent_tool_call_succeeded`, and returns the observation to the expert executor.

The executor records these internal decision phases:

```text
agent_tool_loop       : Agent runs one assigned tool inside the stage.
post_tool_observation : Agent observes the stage/internal-node result and may pass through, add review metadata, request replan, downgrade weak-evidence candidates, or guard final delivery.
```

## Agent-to-Agent handoff

`app/agents/handoff.py` defines package artifacts and handoff rules.

Package artifacts:

```text
context_evidence_package
process_diagnosis_package
governance_package
business_case_package
evaluation_package
delivery_package
```

Example handoff:

```json
{
  "from_agent": "business_case_agent",
  "to_agent": "evaluation_critic_agent",
  "source_stage": "business_case_agent",
  "source_nodes": ["roi_cost", "priority_ranking"],
  "payload_keys": ["roi_cost", "priority_ranking"],
  "handoff_reason": "Evaluation & Critic Agent must validate ranked candidates before delivery."
}
```

## Runtime contract binding

`app/agents/runtime.py` maps internal graph nodes to Expert Agents through `NODE_AGENT_BINDINGS`.

Each binding includes:

```json
{
  "agent_id": "process_diagnosis_agent",
  "capability": "data_readiness_scoring",
  "node_role": "데이터 접근성, 문서 연결성, 접근권한 기반 readiness 분류"
}
```

Example `agent_contracts` item:

```json
{
  "node_name": "data_readiness",
  "agent_id": "process_diagnosis_agent",
  "agent_name": "Process Diagnosis Agent",
  "capability": "data_readiness_scoring",
  "candidate_tools": ["data_readiness_scorer", "data_gap_detector"],
  "selected_tool": "data_readiness_scorer",
  "agent_loop_mode": "expert_agent_supervisor_loop",
  "loop_limit": 2,
  "post_decision": {
    "decision": "pass_through",
    "changed_output": false
  }
}
```

Example `agent_supervisor_steps` item:

```json
{
  "supervisor_agent_id": "ax_delivery_supervisor_agent",
  "delegated_to": "business_case_agent",
  "delegated_stage": "business_case_agent",
  "delegated_nodes": ["roi_cost", "priority_ranking"],
  "input_keys": ["process_analysis", "data_readiness", "automation_feasibility", "risk_governance", "compliance_assessment"],
  "expected_output_keys": ["roi_cost", "priority_ranking"]
}
```

## State output

`python -m app.main --project-id <project_id> --auto-approve --verbose` saves the final workflow state to:

```text
outputs/workflow_state_real.json
```

The state should contain:

```json
{
  "agent_registry": [{"id": "context_evidence_agent", "role_prompt": "...", "tool_specs": ["..."]}],
  "agent_contracts": [{"node_name": "data_readiness", "candidate_tools": ["data_readiness_scorer", "data_gap_detector"]}],
  "agent_tool_calls": [{"node_name": "data_readiness", "tool_name": "data_readiness_scorer"}],
  "agent_decisions": [{"phase": "post_tool_observation", "changed_output": false}],
  "agent_supervisor_steps": [{"delegated_to": "business_case_agent"}],
  "agent_handoffs": [{"from_agent": "business_case_agent", "to_agent": "evaluation_critic_agent"}],
  "business_case_package": {"output_keys": ["roi_cost", "priority_ranking"]}
}
```
