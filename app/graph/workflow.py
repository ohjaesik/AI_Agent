# app/graph/workflow.py

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents.agent_llm import (
    build_agent_llm_call_record,
    run_agent_command_prompt,
    run_agent_reflection_prompt,
)
from app.agents.expert_executor import expert_executed_node
from app.agents.handoff import attach_agent_stage_outputs
from app.agents.model_router import SUPERVISOR_AGENT_ID, select_agent_model
from app.agents.registry import get_agent_spec
from app.agents.supervisor_llm import build_supervisor_llm_call_record, run_supervisor_delegation_prompt
from app.core.config import get_settings
from app.graph.node_worker import workerized_node
from app.graph.replan_node import should_continue_after_replan, should_replan
from app.graph.state import AXPlannerState


AGENT_STAGE_NODES: dict[str, list[str]] = {
    "context_evidence_agent": ["load_project_data", "retrieve_context"],
    "process_diagnosis_agent": ["process_analyzer", "data_readiness", "automation_feasibility"],
    "governance_compliance_agent": ["risk_governance", "compliance_assessment"],
    "business_case_agent": ["roi_cost", "priority_ranking"],
    "evaluation_critic_agent": ["agent_evaluator", "llm_critic"],
    "agent_replan": ["agent_replan"],
    "delivery_orchestration_agent": ["human_review", "poc_delivery_planner", "report_writer", "docx_generator"],
}

AGENT_STAGE_TO_AGENT_ID: dict[str, str] = {
    "context_evidence_agent": "context_evidence_agent",
    "process_diagnosis_agent": "process_diagnosis_agent",
    "governance_compliance_agent": "governance_compliance_agent",
    "business_case_agent": "business_case_agent",
    "evaluation_critic_agent": "evaluation_critic_agent",
    "agent_replan": "evaluation_critic_agent",
    "delivery_orchestration_agent": "delivery_orchestration_agent",
}

DEFAULT_AGENT_STAGE_MAX_LOOPS = 2


def resolve_agent_stage_loop_limit(state: dict[str, Any]) -> int:
    try:
        settings = get_settings()
        loop_limit = int(settings.agent_supervisor_max_tool_loops or DEFAULT_AGENT_STAGE_MAX_LOOPS)
    except Exception:
        loop_limit = DEFAULT_AGENT_STAGE_MAX_LOOPS

    loop_limit = max(1, min(loop_limit, DEFAULT_AGENT_STAGE_MAX_LOOPS))
    if state.get("agent_supervisor_extra_loop_enabled"):
        loop_limit += 1
    return loop_limit


def incoming_handoffs_for_agent(state: dict[str, Any], agent_id: str) -> list[dict[str, Any]]:
    return [
        handoff
        for handoff in (state.get("agent_handoffs", []) or [])
        if handoff.get("to_agent") == agent_id
    ]


def merge_stage_result(accumulator: dict[str, Any], node_result: dict[str, Any]) -> dict[str, Any]:
    """Merge internal node outputs inside an Agent-stage node.

    LangGraph reducers merge across graph nodes, but here several old nodes run
    inside one Agent node. Preserve list-like trace fields instead of replacing
    them with the last internal node's value.
    """
    merged = dict(accumulator)
    list_keys = {
        "audit_logs",
        "errors",
        "agent_contracts",
        "agent_tool_calls",
        "agent_decisions",
        "agent_loop_iterations",
        "agent_loop_requests",
        "agent_supervisor_steps",
        "agent_handoffs",
        "agent_llm_calls",
        "agent_commands",
        "agent_model_decisions",
        "agent_supervisor_delegations",
    }
    for key, value in node_result.items():
        if key in list_keys:
            merged[key] = list(merged.get(key, [])) + list(value or [])
        else:
            merged[key] = value
    return merged


def latest_loop_index(result: dict[str, Any]) -> int | None:
    iterations = result.get("agent_loop_iterations") or []
    if not iterations:
        return None
    return iterations[-1].get("loop_index")


def build_agent_stage_loop_request(stage_name: str, agent_id: str, reflection: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    project_id = state.get("project_id")
    command = "python -m app.main --auto-approve --allow-agent-extra-loop"
    if project_id:
        command += f" --project-id {project_id}"
    return {
        "stage_name": stage_name,
        "agent_id": agent_id,
        "reason": reflection.get("reason"),
        "requested_by": "expert_agent_llm_reflection",
        "requested_extra_loops": 1,
        "command": command,
        "default_action": "skip_extra_loop_and_continue",
    }


def expert_agent_stage(stage_name: str):
    """Create one LLM-command-driven LangGraph node for one Expert Agent.

    The top-level graph moves by Agent stage. At the start of each stage, the
    owning Expert Agent receives a prompt with its role, handoff context, assigned
    internal nodes, and assigned tools. The Agent returns a node command plan, the
    runtime executes only those assigned nodes/tools, then the Agent receives a
    reflection prompt and decides whether to hand off or request another bounded loop.
    """
    internal_nodes = AGENT_STAGE_NODES[stage_name]
    agent_id = AGENT_STAGE_TO_AGENT_ID[stage_name]
    agent_spec = get_agent_spec(agent_id) or {"id": agent_id, "name": agent_id}
    internal_runners = {
        node_name: expert_executed_node(node_name, workerized_node(node_name))
        for node_name in internal_nodes
    }

    def _agent_node(state: dict[str, Any]) -> dict[str, Any]:
        stage_state = dict(state)
        stage_result: dict[str, Any] = {}
        executed_nodes_all: list[str] = []
        loop_limit = resolve_agent_stage_loop_limit(state)

        for stage_loop_index in range(1, loop_limit + 1):
            # 실제 LangGraph에는 별도 Supervisor LLM 노드가 없지만, 모델
            # 선택 정책의 책임 주체는 Supervisor다. 따라서 먼저 Supervisor
            # 자신의 상위 모델 배정을 trace에 남기고, 이어서 위임받은
            # Expert Agent의 command/reflection 모델을 수식으로 선택한다.
            supervisor_assignment = select_agent_model(
                agent_id=SUPERVISOR_AGENT_ID,
                stage_name=stage_name,
                call_kind="supervisor_delegation",
                state=stage_state,
            )
            supervisor_delegation = run_supervisor_delegation_prompt(
                agent_spec=agent_spec,
                stage_name=stage_name,
                internal_nodes=internal_nodes,
                state=stage_state,
                incoming_handoffs=incoming_handoffs_for_agent(stage_state, agent_id),
                loop_index=stage_loop_index,
                model_assignment=supervisor_assignment,
            )
            supervisor_delegation["loop_index"] = stage_loop_index
            supervisor_call_record = build_supervisor_llm_call_record(supervisor_delegation)
            supervisor_retry_assignments = list(supervisor_delegation.get("model_retry_assignments", []) or [])

            command_model_assignment = select_agent_model(
                agent_id=agent_id,
                stage_name=stage_name,
                call_kind="agent_command",
                state={**stage_state, "current_supervisor_delegation": supervisor_delegation},
            )
            stage_result = merge_stage_result(
                stage_result,
                {
                    "agent_model_decisions": [supervisor_assignment, *supervisor_retry_assignments, command_model_assignment],
                    "agent_supervisor_delegations": [supervisor_delegation],
                    "agent_llm_calls": [supervisor_call_record],
                    "current_supervisor_delegation": supervisor_delegation,
                    "supervisor_approval_policy": supervisor_delegation.get("human_approval_policy", {}),
                },
            )
            stage_state = {
                **stage_state,
                "current_supervisor_model_assignment": supervisor_assignment,
                "current_supervisor_delegation": supervisor_delegation,
                "supervisor_approval_policy": supervisor_delegation.get("human_approval_policy", {}),
                "current_agent_model_assignment": command_model_assignment,
                "agent_model_decisions": list(stage_state.get("agent_model_decisions", []))
                + [supervisor_assignment, *supervisor_retry_assignments, command_model_assignment],
                "agent_supervisor_delegations": list(stage_state.get("agent_supervisor_delegations", [])) + [supervisor_delegation],
                "agent_llm_calls": list(stage_state.get("agent_llm_calls", [])) + [supervisor_call_record],
            }

            command = run_agent_command_prompt(
                agent_spec=agent_spec,
                stage_name=stage_name,
                internal_nodes=internal_nodes,
                state=stage_state,
                incoming_handoffs=incoming_handoffs_for_agent(stage_state, agent_id),
                loop_index=stage_loop_index,
                model_assignment=command_model_assignment,
                supervisor_delegation=supervisor_delegation,
            )
            command_record = build_agent_llm_call_record("agent_command", command)
            command_retry_assignments = list(command.get("model_retry_assignments", []) or [])
            stage_result = merge_stage_result(
                stage_result,
                {
                    "agent_model_decisions": command_retry_assignments,
                    "agent_llm_calls": [command_record],
                    "agent_commands": [command],
                },
            )
            stage_state = {
                **stage_state,
                "current_agent_command": command,
                "agent_model_decisions": list(stage_state.get("agent_model_decisions", [])) + command_retry_assignments,
                "agent_llm_calls": list(stage_state.get("agent_llm_calls", [])) + [command_record],
            }

            executed_nodes: list[str] = []
            for node_name in command.get("node_order", internal_nodes):
                if node_name not in internal_runners:
                    continue
                node_result = internal_runners[node_name](stage_state)
                stage_result = merge_stage_result(stage_result, node_result)
                stage_state = {**stage_state, **node_result}
                executed_nodes.append(node_name)
                executed_nodes_all.append(node_name)

            reflection_model_assignment = select_agent_model(
                agent_id=agent_id,
                stage_name=stage_name,
                call_kind="agent_reflection",
                state={**stage_state, **stage_result},
            )
            stage_result = merge_stage_result(
                stage_result,
                {
                    "agent_model_decisions": [reflection_model_assignment],
                },
            )
            stage_state = {
                **stage_state,
                "current_agent_model_assignment": reflection_model_assignment,
                "agent_model_decisions": list(stage_state.get("agent_model_decisions", [])) + [reflection_model_assignment],
            }

            reflection = run_agent_reflection_prompt(
                agent_spec=agent_spec,
                stage_name=stage_name,
                agent_command=command,
                executed_nodes=executed_nodes,
                state=state,
                result=stage_result,
                loop_index=stage_loop_index,
                model_assignment=reflection_model_assignment,
                supervisor_delegation=supervisor_delegation,
            )
            reflection_record = build_agent_llm_call_record("agent_reflection", reflection)
            reflection_retry_assignments = list(reflection.get("model_retry_assignments", []) or [])
            stage_result = merge_stage_result(
                stage_result,
                {
                    "agent_model_decisions": reflection_retry_assignments,
                    "agent_llm_calls": [reflection_record],
                    "agent_commands": [reflection],
                },
            )
            stage_state = {
                **stage_state,
                "current_agent_reflection": reflection,
                "agent_model_decisions": list(stage_state.get("agent_model_decisions", [])) + reflection_retry_assignments,
                "agent_llm_calls": list(stage_state.get("agent_llm_calls", [])) + [reflection_record],
            }

            if not bool(reflection.get("needs_iteration")):
                break
            if stage_loop_index >= loop_limit:
                requests = list(stage_result.get("agent_loop_requests", []))
                requests.append(build_agent_stage_loop_request(stage_name, agent_id, reflection, state))
                stage_result["agent_loop_requests"] = requests
                break

        return attach_agent_stage_outputs(
            state=state,
            result=stage_result,
            agent_id=agent_id,
            stage_name=stage_name,
            executed_nodes=executed_nodes_all,
            loop_index=latest_loop_index(stage_result),
        )

    _agent_node.__name__ = f"agent_stage_{stage_name}"
    return _agent_node


def build_ax_planner_graph():
    builder = StateGraph(AXPlannerState)

    builder.add_node("context_evidence_agent", expert_agent_stage("context_evidence_agent"))
    builder.add_node("process_diagnosis_agent", expert_agent_stage("process_diagnosis_agent"))
    builder.add_node("governance_compliance_agent", expert_agent_stage("governance_compliance_agent"))
    builder.add_node("business_case_agent", expert_agent_stage("business_case_agent"))
    builder.add_node("evaluation_critic_agent", expert_agent_stage("evaluation_critic_agent"))
    builder.add_node("agent_replan", expert_agent_stage("agent_replan"))
    builder.add_node("delivery_orchestration_agent", expert_agent_stage("delivery_orchestration_agent"))

    builder.add_edge(START, "context_evidence_agent")

    # Context/Evidence package is handed to both diagnostic and governance Agents.
    builder.add_edge("context_evidence_agent", "process_diagnosis_agent")
    builder.add_edge("context_evidence_agent", "governance_compliance_agent")

    # Business Case Agent waits for diagnosis and governance packages.
    builder.add_edge(
        ["process_diagnosis_agent", "governance_compliance_agent"],
        "business_case_agent",
    )

    # Evaluation & Critic Agent validates the ranked business-case package.
    builder.add_edge("business_case_agent", "evaluation_critic_agent")

    # If the critic requests evidence refresh, the Evaluation Agent performs a bounded replan
    # and hands control back to Context & Evidence. Otherwise, delivery starts.
    builder.add_conditional_edges(
        "evaluation_critic_agent",
        should_replan,
        {
            "agent_replan": "agent_replan",
            "human_review": "delivery_orchestration_agent",
        },
    )
    builder.add_conditional_edges(
        "agent_replan",
        should_continue_after_replan,
        {
            "retrieve_context": "context_evidence_agent",
            "human_review": "delivery_orchestration_agent",
        },
    )

    builder.add_edge("delivery_orchestration_agent", END)

    return builder.compile(checkpointer=InMemorySaver())
