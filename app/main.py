# app/main.py

from __future__ import annotations

import argparse
import pprint
from typing import Any

from langgraph.types import Command

from app.graph.workflow import build_ax_planner_graph


def print_interrupt(result: dict[str, Any]) -> None:
    interrupts = result.get("__interrupt__")

    if not interrupts:
        return

    print("\n=== HUMAN REVIEW INTERRUPT ===")
    pprint.pp(interrupts)


def run_demo(
    project_id: int,
    company_id: int,
    thread_id: str,
    auto_approve: bool,
) -> dict[str, Any]:
    graph = build_ax_planner_graph()

    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }
    initial_state = {
        "project_id": project_id,
        "company_id": company_id,
        "user_request": (
            "제조기업의 업무 프로세스와 내부 문서를 분석하여 "
            "AI Agent 도입 후보를 도출하고 PoC 우선순위 보고서를 생성한다."
        ),
        "report_requirements": {
            "title": "제조기업 AX 전환 업무 프로세스 진단 및 AI Agent 도입 우선순위 추천 보고서",
            "author": "오재식",
            "date": "2026-07",
        },
        "audit_logs": [],
        "errors": [],
    }

    print("=== AX Delivery Planner Graph Start ===")
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

    print("\n=== Top Candidates ===")
    for item in result.get("priority_ranking", {}).get("items", [])[:5]:
        print(
            f"{item.get('rank')}. "
            f"{item.get('candidate_agent_name')} | "
            f"score={item.get('final_score')} | "
            f"status={item.get('status')} | "
            f"saving={item.get('saving_rate')}%"
        )

    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", type=int, default=4)
    parser.add_argument("--company-id", type=int, default=4)
    parser.add_argument("--thread-id", type=str, default="ax-planner-demo-001")
    parser.add_argument("--auto-approve", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    run_demo(
        project_id=args.project_id,
        company_id=args.company_id,
        thread_id=args.thread_id,
        auto_approve=args.auto_approve,
    )