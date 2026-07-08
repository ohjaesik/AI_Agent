# app/main.py

from __future__ import annotations

import argparse
import json
import pprint
from typing import Any

from langgraph.types import Command

from app.db.crud import resolve_project_selection
from app.db.database import SessionLocal
from app.graph.workflow import build_ax_planner_graph


def print_interrupt(result: dict[str, Any]) -> None:
    interrupts = result.get("__interrupt__")

    if not interrupts:
        return

    print("\n=== HUMAN REVIEW INTERRUPT ===")
    pprint.pp(interrupts)


def resolve_ids(
    project_id: int | None,
    company_id: int | None,
) -> dict[str, int]:
    with SessionLocal() as db:
        return resolve_project_selection(
            db=db,
            project_id=project_id,
            company_id=company_id,
        )


def compact_payload(payload: Any, max_chars: int = 700) -> str:
    try:
        text = json.dumps(payload or {}, ensure_ascii=False, default=str)
    except TypeError:
        text = str(payload)

    if len(text) <= max_chars:
        return text

    return text[:max_chars] + "..."


def print_execution_trace(result: dict[str, Any]) -> None:
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
    print("\n=== State Summary ===")
    print("business_processes:", len(result.get("business_processes", [])))
    print("documents:", len(result.get("documents", [])))
    print("retrieved_context_groups:", len(result.get("retrieved_contexts", {})))
    print("evidence_items:", len(result.get("evidence_items", [])))
    print("used_sources:", len(result.get("used_sources", [])))
    print("report_sections:", len(result.get("report_data", {}).get("sections", [])))


def run_demo(
    project_id: int | None,
    company_id: int | None,
    thread_id: str,
    auto_approve: bool,
    report_title: str | None = None,
    report_author: str | None = None,
    report_date: str | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    resolved = resolve_ids(project_id=project_id, company_id=company_id)
    resolved_project_id = resolved["project_id"]
    resolved_company_id = resolved["company_id"]

    graph = build_ax_planner_graph()

    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    initial_state = {
        "project_id": resolved_project_id,
        "company_id": resolved_company_id,
        "user_request": (
            "제조기업의 업무 프로세스와 내부 문서를 분석하여 "
            "AI Agent 도입 후보를 도출하고 PoC 우선순위 보고서를 생성한다."
        ),
        "report_requirements": {
            "title": report_title
            or "제조기업 AX 전환 업무 프로세스 진단 및 AI Agent 도입 우선순위 추천 보고서",
            "author": report_author or "",
            "date": report_date or "",
        },
        "audit_logs": [],
        "errors": [],
    }

    print("=== AX Delivery Planner Graph Start ===")
    print(f"project_id={resolved_project_id}, company_id={resolved_company_id}")
    print(f"thread_id={thread_id}")

    result = graph.invoke(initial_state, config=config)

    if "__interrupt__" in result:
        print_interrupt(result)

        if not auto_approve:
            print("\nGraph paused. Resume with a human decision in code or run with --auto-approve.")
            return result

        human_decision = {
            "reviewer_name": "IT기획팀 담당자",
            "decision": "approve",
            "comment": (
                "v1 데모 실행을 위해 자동 승인한다. "
                "실제 운영에서는 IT기획팀, 현업 부서장, 보안 담당자 검토가 필요하다."
            ),
            "edited_payload": None,
        }

        print("\n=== Auto Resume With Human Decision ===")
        print(compact_payload(human_decision))

        result = graph.invoke(
            Command(resume=human_decision),
            config=config,
        )

    print("\n=== AX Delivery Planner Graph Finished ===")
    print("report_docx_path:", result.get("report_docx_path"))

    if result.get("errors"):
        print("\n=== Errors ===")
        for error in result["errors"]:
            print("-", error)

    print_report_generation_summary(result)

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
    parser.add_argument("--thread-id", type=str, default="ax-planner-demo-001")
    parser.add_argument("--auto-approve", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--report-title", type=str, default=None)
    parser.add_argument("--report-author", type=str, default=None)
    parser.add_argument("--report-date", type=str, default=None)
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
        verbose=args.verbose,
    )
