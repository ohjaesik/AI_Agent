# app/graph/workflow.py
"""AX 분석용 LangGraph workflow를 Expert Agent 단위로 구성한다.

이 파일은 "어떤 Agent가 어떤 내부 node를 실행하고, 어떤 순서로 handoff되는지"를
정의하는 최상위 orchestration 코드다. 기존에는 `load_project_data`,
`retrieve_context` 같은 node가 직접 그래프에 붙어 있었지만, 현재 구조에서는
여러 내부 node를 하나의 Expert Agent stage로 묶고 다음 순서로 실행한다.

stage 실행 흐름:
1. Supervisor 모델을 선택한다.
2. Supervisor LLM이 해당 Expert Agent에 위임장/tool policy를 만든다.
3. Expert Agent command LLM이 내부 node 실행 순서를 정한다.
4. runtime이 허용된 내부 node/tool만 실행한다.
5. Expert Agent reflection LLM이 결과가 충분한지 판단한다.
6. Supervisor autonomy policy가 extra loop 또는 handoff를 최종 결정한다.
7. handoff/package trace를 state에 남긴다.
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents.agent_llm import (
    build_agent_llm_call_record,
    run_agent_command_prompt,
    run_agent_reflection_prompt,
)
from app.agents.autonomy import build_supervisor_loop_decision, resolve_stage_loop_limit
from app.agents.expert_executor import expert_executed_node
from app.agents.handoff import attach_agent_stage_outputs
from app.agents.model_router import SUPERVISOR_AGENT_ID, select_agent_model
from app.agents.registry import get_agent_spec
from app.agents.supervisor_llm import build_supervisor_llm_call_record, run_supervisor_delegation_prompt
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

# LangGraph node 이름과 실제 Agent registry ID가 항상 1:1은 아니다.
# 예를 들어 `agent_replan` stage는 별도 Agent가 아니라 Evaluation & Critic Agent의
# 재계획 책임으로 실행된다. 이 매핑은 stage 실행 시 어떤 AgentSpec/prompt를
# 사용할지 결정한다.
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
    """현재 state의 자율성 정책을 기준으로 stage 반복 상한을 계산한다."""

    return resolve_stage_loop_limit(state, default_base_limit=DEFAULT_AGENT_STAGE_MAX_LOOPS)


def incoming_handoffs_for_agent(state: dict[str, Any], agent_id: str) -> list[dict[str, Any]]:
    """현재 Agent가 이전 Agent에게 받은 handoff만 골라 prompt context로 넘긴다."""

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
        "agent_autonomy_loop_decisions",
    }
    for key, value in node_result.items():
        if key in list_keys:
            merged[key] = list(merged.get(key, [])) + list(value or [])
        else:
            merged[key] = value
    return merged


def latest_loop_index(result: dict[str, Any]) -> int | None:
    """stage 내부 tool loop trace 중 마지막 loop 번호를 handoff trace에 넣기 위해 읽는다."""

    iterations = result.get("agent_loop_iterations") or []
    if not iterations:
        return None
    return iterations[-1].get("loop_index")


def build_agent_stage_loop_request(stage_name: str, agent_id: str, reflection: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """loop 상한 때문에 더 반복하지 못한 경우 사용자가 재실행할 수 있는 힌트를 남긴다.

    현재 기본 정책은 extra loop가 켜져 있어 대부분 자동으로 처리된다. 그래도 상한에
    걸렸을 때는 `agent_loop_requests`에 command와 이유를 남겨, 사람이 필요하면 더
    큰 예산/상한으로 다시 돌릴 수 있게 한다.
    """

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
        "default_action": "supervisor_handoff_with_current_best_result",
        "supervisor_loop_decision": state.get("current_supervisor_loop_decision", {}),
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
        """LangGraph가 실제로 호출하는 stage node 함수다.

        `stage_state`는 stage 내부에서 계속 갱신되는 실행 상태이고,
        `stage_result`는 LangGraph에 최종 반환할 변경분이다. 둘을 분리하는 이유는
        내부 node 여러 개가 한 stage 안에서 순차 실행되기 때문에, 중간 결과는 다음
        내부 node와 reflection prompt가 즉시 볼 수 있어야 하지만 LangGraph에는 stage
        종료 시 한 번만 반환되어야 하기 때문이다.
        """

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
            # Supervisor delegation과 Expert command는 서로 다른 LLM 호출이다.
            # Supervisor는 "무엇을 시킬지/어떤 도구를 우선할지"를 정하고,
            # Expert command는 "자기 stage 내부 node를 어떤 순서로 실행할지"를 정한다.
            stage_result = merge_stage_result(
                stage_result,
                {
                    "agent_model_decisions": [supervisor_assignment, *supervisor_retry_assignments, command_model_assignment],
                    "agent_supervisor_delegations": [supervisor_delegation],
                    "agent_llm_calls": [supervisor_call_record],
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
                # 내부 node는 반드시 `internal_runners`에 등록된 것만 실행한다.
                # LLM이 node_order에 이상한 값을 넣어도 여기서 무시되므로 tool 권한 경계가 유지된다.
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
            # reflection은 실행 결과를 본 뒤 "이 stage 산출물이 handoff 가능한지"를 판단한다.
            # 단, 실제 반복 여부의 최종 결정은 아래 Supervisor autonomy policy가 내린다.
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
                state=stage_state,
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

            # Supervisor가 장기 목표, 산출물 부족, Agent reflection, 비용 예산,
            # loop 상한을 함께 보고 stage를 한 번 더 돌릴지 결정한다.
            # 이 trace가 있어야 "왜 자율적으로 반복/중단했는지"를 나중에 검증할 수 있다.
            loop_decision = build_supervisor_loop_decision(
                stage_name=stage_name,
                agent_id=agent_id,
                loop_index=stage_loop_index,
                loop_limit=loop_limit,
                state=stage_state,
                result=stage_result,
                reflection=reflection,
            )
            stage_result = merge_stage_result(
                stage_result,
                {"agent_autonomy_loop_decisions": [loop_decision]},
            )
            stage_state = {
                **stage_state,
                "current_supervisor_loop_decision": loop_decision,
                "agent_autonomy_loop_decisions": list(stage_state.get("agent_autonomy_loop_decisions", [])) + [loop_decision],
            }

            if not bool(loop_decision.get("should_iterate")):
                if loop_decision.get("decision") == "loop_limit_reached":
                    requests = list(stage_result.get("agent_loop_requests", []))
                    requests.append(build_agent_stage_loop_request(stage_name, agent_id, reflection, stage_state))
                    stage_result["agent_loop_requests"] = requests
                break

        return attach_agent_stage_outputs(
            state=stage_state,
            result=stage_result,
            agent_id=agent_id,
            stage_name=stage_name,
            executed_nodes=executed_nodes_all,
            loop_index=latest_loop_index(stage_result),
        )

    _agent_node.__name__ = f"agent_stage_{stage_name}"
    return _agent_node


def build_ax_planner_graph():
    """AX 분석 그래프를 생성한다.

    병렬 구간:
    - Context/Evidence 이후 Process Diagnosis와 Governance/Compliance는 동시에 돌 수 있다.

    fan-in 구간:
    - Business Case는 진단 결과와 거버넌스 결과를 모두 기다린 뒤 실행된다.

    조건부 구간:
    - Evaluation/Critic이 추가 근거가 필요하다고 판단하면 bounded replan으로 가고,
      그렇지 않으면 Delivery Orchestration으로 넘어간다.
    """

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
