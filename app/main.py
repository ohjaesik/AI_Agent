# app/main.py
"""AX Delivery Planner CLI 실행 진입점이다.

이 파일은 사용자가 터미널에서 `python -m app.main ...`으로 분석 workflow를 실행할 때
가장 먼저 호출된다. 주요 역할은 다음과 같다.

- project/company id를 DB에서 해석한다.
- LangGraph 초기 state를 만든다.
- Supervisor 장기 목표와 자율성 정책을 state에 넣는다.
- Human Review interrupt가 발생하면 CLI auto-approve 옵션에 따라 resume한다.
- 최종 workflow_state JSON과 DOCX 보고서 경로, Agent trace 요약을 출력한다.

실제 분석 로직은 `app/graph/workflow.py`와 각 node/tool에 있고, 이 파일은 실행 옵션과
결과 저장/요약 출력에 집중한다.
"""

from __future__ import annotations

import argparse
import json
import pprint
from pathlib import Path
from typing import Any

from langgraph.types import Command

from app.agents.autonomy import (
    build_supervisor_autonomy_policy,
    build_supervisor_long_term_goal,
    resolve_extra_loop_enabled,
)
from app.agents.cost_summary import build_total_cost_summary
from app.agents.registry import get_agent_registry
from app.db.crud import resolve_project_selection
from app.db.database import SessionLocal
from app.graph.workflow import build_ax_planner_graph


DEFAULT_STATE_OUTPUT_PATH = "outputs/workflow_state_real.json"


def print_interrupt(result: dict[str, Any]) -> None:
    """LangGraph interrupt payload를 CLI에 보기 좋게 출력한다."""

    interrupts = result.get("__interrupt__")

    if not interrupts:
        return

    print("\n=== HUMAN REVIEW INTERRUPT ===")
    pprint.pp(interrupts)


def resolve_ids(
    project_id: int | None,
    company_id: int | None,
) -> dict[str, int]:
    """CLI에서 받은 project_id/company_id를 실제 실행 가능한 ID로 정규화한다."""

    with SessionLocal() as db:
        return resolve_project_selection(
            db=db,
            project_id=project_id,
            company_id=company_id,
        )


def save_workflow_state(result: dict[str, Any], output_path: str | Path | None) -> str | None:
    """workflow 최종 state를 JSON 파일로 저장한다.

    이 JSON은 실행 검증에서 가장 중요한 산출물이다. Supervisor delegation,
    model decision, RAG query plan, autonomy loop decision, human review 기록이 모두
    들어가므로 실행 후 디버깅/보고서 근거 확인에 사용한다.
    """

    if not output_path:
        return None

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return str(path)


def attach_cli_observability_summary(result: dict[str, Any]) -> dict[str, Any]:
    """CLI 저장 직전에 누락될 수 있는 top-level 관찰성 요약을 보강한다.

    정상 완료 시에는 graph의 finalizer가 `total_cost_summary`를 넣는다. 다만 Human
    Review interrupt처럼 중간 저장되는 state는 finalizer까지 도달하지 않으므로,
    CLI 출력 JSON에는 항상 같은 키가 존재하도록 한 번 더 보강한다.
    """

    if "total_cost_summary" not in result:
        result = dict(result)
        result["total_cost_summary"] = build_total_cost_summary(list(result.get("agent_model_decisions", []) or []))
    return result


def compact_payload(payload: Any, max_chars: int = 700) -> str:
    """CLI 출력이 너무 길어지지 않도록 dict/list payload를 짧게 줄인다."""

    try:
        text = json.dumps(payload or {}, ensure_ascii=False, default=str)
    except TypeError:
        text = str(payload)

    if len(text) <= max_chars:
        return text

    return text[:max_chars] + "..."


def print_execution_trace(result: dict[str, Any]) -> None:
    """audit_logs를 사람이 읽기 좋은 순서형 실행 trace로 출력한다."""

    audit_logs = result.get("audit_logs", [])

    print("\n=== Execution Trace ===")

    if not audit_logs:
        print("No audit logs in graph state.")
        return

    for idx, log in enumerate(audit_logs, start=1):
        node = log.get("node")
        status = log.get("status")
        timestamp = log.get("timestamp")
        payload = compact_payload(log.get("payload"))
        print(f"{idx:02d}. [{status}] {node} @ {timestamp}")
        print(f"    payload={payload}")


def print_report_generation_summary(result: dict[str, Any]) -> None:
    """보고서 생성 방식, citation validation 결과, fallback 경고를 출력한다."""

    report_data = result.get("report_data", {})
    generation = report_data.get("generation", {})
    citation_validation = report_data.get("citation_validation", {})

    print("\n=== Report Generation ===")
    print("mode:", generation.get("mode", "unknown"))

    if generation.get("model"):
        print("model:", generation.get("model"))

    if generation.get("reason"):
        print("fallback_reason:", generation.get("reason"))

    if generation.get("warnings"):
        print("warnings:", compact_payload(generation.get("warnings")))

    if citation_validation:
        print("citation_valid:", citation_validation.get("valid"))
        print("allowed_citations:", citation_validation.get("allowed_count"))
        print("found_citations:", citation_validation.get("found_count"))
        print("invalid_labels:", citation_validation.get("invalid_labels"))
        print("paragraphs_without_citation:", citation_validation.get("paragraphs_without_citation"))


def print_state_summary(result: dict[str, Any]) -> None:
    """최종 state에 어떤 주요 산출물이 몇 개 들어있는지 요약한다."""

    print("\n=== State Summary ===")
    print("business_processes:", len(result.get("business_processes", [])))
    print("documents:", len(result.get("documents", [])))
    print("retrieved_context_groups:", len(result.get("retrieved_contexts", {})))
    print("evidence_items:", len(result.get("evidence_items", [])))
    print("used_sources:", len(result.get("used_sources", [])))
    print("agent_registry:", len(result.get("agent_registry", [])))
    print("agent_contracts:", len(result.get("agent_contracts", [])))
    print("agent_tool_calls:", len(result.get("agent_tool_calls", [])))
    print("agent_loop_iterations:", len(result.get("agent_loop_iterations", [])))
    print("agent_loop_requests:", len(result.get("agent_loop_requests", [])))
    print("agent_supervisor_steps:", len(result.get("agent_supervisor_steps", [])))
    print("agent_handoffs:", len(result.get("agent_handoffs", [])))
    print("agent_llm_calls:", len(result.get("agent_llm_calls", [])))
    print("agent_commands:", len(result.get("agent_commands", [])))
    print("agent_model_decisions:", len(result.get("agent_model_decisions", [])))
    print("estimated_total_cost_usd:", result.get("total_cost_summary", {}).get("estimated_total_cost_usd"))
    print("agent_supervisor_delegations:", len(result.get("agent_supervisor_delegations", [])))
    print("agent_autonomy_loop_decisions:", len(result.get("agent_autonomy_loop_decisions", [])))
    print("agent_packages:", len([key for key in result if key.endswith("_package")]))
    print("report_sections:", len(result.get("report_data", {}).get("sections", [])))


def print_agent_handoff_summary(result: dict[str, Any]) -> None:
    """최근 Agent handoff 흐름을 짧게 출력한다."""

    handoffs = result.get("agent_handoffs", []) or []
    if not handoffs:
        return

    print("\n=== Agent Handoffs ===")
    for idx, handoff in enumerate(handoffs[-10:], start=max(1, len(handoffs) - 9)):
        print(
            f"{idx}. {handoff.get('from_agent')} -> {handoff.get('to_agent')} | "
            f"payload={handoff.get('payload_keys')}"
        )


def print_agent_llm_summary(result: dict[str, Any]) -> None:
    """Supervisor/Expert Agent LLM 호출 성공 여부와 최근 호출 이유를 출력한다."""

    calls = result.get("agent_llm_calls", []) or []
    if not calls:
        return

    used_count = sum(1 for call in calls if call.get("llm_used"))
    print("\n=== Agent LLM Commands ===")
    print(f"llm_used={used_count}/{len(calls)}")
    for idx, call in enumerate(calls[-12:], start=max(1, len(calls) - 11)):
        print(
            f"{idx}. {call.get('kind')} | agent={call.get('agent_id')} | "
            f"stage={call.get('stage_name')} | llm_used={call.get('llm_used')} | "
            f"mode={call.get('mode')} | reason={call.get('reason')}"
        )


def print_agent_loop_requests(result: dict[str, Any]) -> None:
    """loop 상한 등으로 자동 반복하지 못한 경우 재실행 힌트를 출력한다."""

    requests = result.get("agent_loop_requests", []) or []
    if not requests:
        return

    print("\n=== Agent Loop Requests ===")
    for idx, request in enumerate(requests, start=1):
        node_or_stage = request.get("node_name") or request.get("stage_name")
        print(f"{idx}. node_or_stage={node_or_stage} agent={request.get('agent_id')}")
        print(f"   reason={request.get('reason')}")
        print(f"   command={request.get('command')}")
        print(f"   default_action={request.get('default_action')}")


def print_supervisor_autonomy_summary(result: dict[str, Any]) -> None:
    """Supervisor가 각 stage에서 iterate/handoff를 어떻게 판단했는지 출력한다."""

    decisions = result.get("agent_autonomy_loop_decisions", []) or []
    if not decisions:
        return

    print("\n=== Supervisor Autonomy ===")
    policy = result.get("supervisor_autonomy_policy", {}) or {}
    print("enabled:", policy.get("enabled"))
    print("extra_loop_enabled:", result.get("agent_supervisor_extra_loop_enabled"))
    print("loop_decisions:", len(decisions))
    for idx, decision in enumerate(decisions[-10:], start=max(1, len(decisions) - 9)):
        print(
            f"{idx}. stage={decision.get('stage_name')} loop={decision.get('loop_index')}/{decision.get('loop_limit')} | "
            f"decision={decision.get('decision')} | reasons={decision.get('iteration_reasons')}"
        )


def build_cli_human_decision(
    reviewer_name: str,
    review_decision: str,
    review_comment: str | None,
) -> dict[str, Any]:
    """`--auto-approve` 실행 시 Human Review interrupt에 넣을 CLI 결정 payload를 만든다."""

    default_comment = (
        "CLI 실행 옵션에 따라 우선순위 결과를 승인 처리하였다. "
        "운영 적용 전에는 현업 부서, IT기획, 보안/거버넌스 담당자의 검토 기록을 별도로 남겨야 한다."
    )

    return {
        "reviewer_name": reviewer_name,
        "decision": review_decision,
        "comment": review_comment or default_comment,
        "edited_payload": None,
        "review_channel": "cli",
    }


def run_demo(
    project_id: int | None,
    company_id: int | None,
    thread_id: str,
    auto_approve: bool,
    report_title: str | None = None,
    report_author: str | None = None,
    report_date: str | None = None,
    report_status: str | None = None,
    reviewer_name: str = "IT기획팀 담당자",
    review_decision: str = "approve",
    review_comment: str | None = None,
    verbose: bool = False,
    state_output_path: str | None = None,
    allow_agent_extra_loop: bool | None = None,
    supervisor_goal: str | None = None,
) -> dict[str, Any]:
    """AX 분석 workflow를 한 번 실행한다.

    실행 흐름:
    1. project/company id를 확정한다.
    2. 보고서 요구사항과 Supervisor 장기 목표를 만든다.
    3. LangGraph 초기 state를 구성한다.
    4. graph.invoke로 workflow를 실행한다.
    5. Human Review interrupt가 있고 auto_approve면 자동 review payload로 resume한다.
    6. 최종 state를 저장하고 요약을 출력한다.
    """

    resolved = resolve_ids(project_id=project_id, company_id=company_id)
    resolved_project_id = resolved["project_id"]
    resolved_company_id = resolved["company_id"]

    graph = build_ax_planner_graph()

    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    normalized_report_status = report_status or ("reviewed" if auto_approve else "draft")
    # allow_agent_extra_loop가 None이면 .env의 자율성 설정을 따른다.
    # 현재 기본값은 controlled autonomous mode라 extra loop가 켜진다.
    resolved_extra_loop = resolve_extra_loop_enabled(allow_agent_extra_loop)
    workflow_user_request = (
        "제조기업의 업무 프로세스와 공식/내부 문서를 분석하여 "
        "AI Agent 도입 후보를 도출하고 PoC 우선순위 보고서를 생성한다."
    )
    report_requirements = {
        "title": report_title
        or "제조기업 AX 전환 업무 프로세스 진단 및 AI Agent 도입 우선순위 추천 보고서",
        "author": report_author or "",
        "date": report_date or "",
        "status": normalized_report_status,
    }
    supervisor_long_term_goal = build_supervisor_long_term_goal(
        user_request=workflow_user_request,
        report_requirements=report_requirements,
        explicit_goal=supervisor_goal,
    )
    # 이 policy는 prompt에도 들어가고 Python runtime의 loop 판단에도 쓰인다.
    # 따라서 LLM이 이해하는 자율성 범위와 실제 코드가 적용하는 자율성 범위를 맞춘다.
    supervisor_autonomy_policy = build_supervisor_autonomy_policy(extra_loop_enabled=resolved_extra_loop)

    initial_state = {
        "project_id": resolved_project_id,
        "company_id": resolved_company_id,
        "user_request": workflow_user_request,
        "report_requirements": report_requirements,
        "agent_registry": get_agent_registry(),
        "agent_contracts": [],
        "agent_tool_calls": [],
        "agent_tool_validations": [],
        "agent_decisions": [],
        "agent_loop_iterations": [],
        "agent_loop_requests": [],
        "agent_supervisor_steps": [],
        "agent_handoffs": [],
        "agent_llm_calls": [],
        "agent_commands": [],
        "agent_model_decisions": [],
        "agent_supervisor_delegations": [],
        "agent_autonomy_loop_decisions": [],
        "agent_supervisor_extra_loop_enabled": resolved_extra_loop,
        "supervisor_long_term_goal": supervisor_long_term_goal,
        "supervisor_autonomy_policy": supervisor_autonomy_policy,
        "audit_logs": [],
        "errors": [],
    }

    print("=== AX Delivery Planner Graph Start ===")
    print(f"project_id={resolved_project_id}, company_id={resolved_company_id}")
    print(f"thread_id={thread_id}")
    print(f"report_status={normalized_report_status}")
    print(f"allow_agent_extra_loop={resolved_extra_loop}")
    print(f"supervisor_goal={supervisor_long_term_goal.get('objective')}")

    result = graph.invoke(initial_state, config=config)
    result = attach_cli_observability_summary(result)

    if "__interrupt__" in result:
        print_interrupt(result)

        if not auto_approve:
            saved_path = save_workflow_state(result, state_output_path)
            if saved_path:
                print("workflow_state_path:", saved_path)
            print("\nGraph paused. Resume with a human decision in code or run with --auto-approve.")
            return result

        human_decision = build_cli_human_decision(
            reviewer_name=reviewer_name,
            review_decision=review_decision,
            review_comment=review_comment,
        )

        print("\n=== Auto Resume With Human Decision ===")
        print(compact_payload(human_decision))

        result = graph.invoke(
            Command(resume=human_decision),
            config=config,
        )
        result = attach_cli_observability_summary(result)

    saved_path = save_workflow_state(result, state_output_path)

    print("\n=== AX Delivery Planner Graph Finished ===")
    print("report_docx_path:", result.get("report_docx_path"))
    if saved_path:
        print("workflow_state_path:", saved_path)

    if result.get("errors"):
        print("\n=== Errors ===")
        for error in result["errors"]:
            print("-", error)

    print_report_generation_summary(result)
    print_agent_handoff_summary(result)
    print_agent_llm_summary(result)
    print_supervisor_autonomy_summary(result)
    print_agent_loop_requests(result)

    print("\n=== Top Candidates ===")
    for item in result.get("priority_ranking", {}).get("items", [])[:5]:
        print(
            f"{item.get('rank')}. "
            f"{item.get('candidate_agent_name')} | "
            f"score={item.get('final_score')} | "
            f"status={item.get('status')} | "
            f"saving={item.get('saving_rate')}%"
        )

    if verbose:
        print_state_summary(result)
        print_execution_trace(result)

    return result


def parse_args() -> argparse.Namespace:
    """CLI argument를 정의한다."""

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project-id",
        type=int,
        default=None,
        help="Analysis project ID. If omitted, the latest project is used.",
    )
    parser.add_argument(
        "--company-id",
        type=int,
        default=None,
        help="Company ID. If omitted, it is resolved from the selected project.",
    )
    parser.add_argument("--thread-id", type=str, default="ax-planner-cli")
    parser.add_argument("--auto-approve", action="store_true")
    extra_loop_group = parser.add_mutually_exclusive_group()
    extra_loop_group.add_argument("--allow-agent-extra-loop", dest="allow_agent_extra_loop", action="store_true", default=None)
    extra_loop_group.add_argument("--disable-agent-extra-loop", dest="allow_agent_extra_loop", action="store_false", default=None)
    parser.add_argument("--supervisor-goal", type=str, default=None)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--report-title", type=str, default=None)
    parser.add_argument("--report-author", type=str, default=None)
    parser.add_argument("--report-date", type=str, default=None)
    parser.add_argument("--report-status", type=str, default=None, choices=["draft", "reviewed", "final"])
    parser.add_argument("--reviewer-name", type=str, default="IT기획팀 담당자")
    parser.add_argument("--review-decision", type=str, default="approve", choices=["approve", "edit", "reject"])
    parser.add_argument("--review-comment", type=str, default=None)
    parser.add_argument("--state-output-path", type=str, default=DEFAULT_STATE_OUTPUT_PATH)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    run_demo(
        project_id=args.project_id,
        company_id=args.company_id,
        thread_id=args.thread_id,
        auto_approve=args.auto_approve,
        report_title=args.report_title,
        report_author=args.report_author,
        report_date=args.report_date,
        report_status=args.report_status,
        reviewer_name=args.reviewer_name,
        review_decision=args.review_decision,
        review_comment=args.review_comment,
        verbose=args.verbose,
        state_output_path=args.state_output_path,
        allow_agent_extra_loop=args.allow_agent_extra_loop,
        supervisor_goal=args.supervisor_goal,
    )
