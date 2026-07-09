# app/tools/report_data_builder.py

from __future__ import annotations

import re
from typing import Any

from app.chains.report_writer import generate_report_data_with_llm


def percent(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%" if float(value) <= 1 else f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "0.0%"


def strip_heading_number(heading: str) -> str:
    return re.sub(r"^\d+\.\s*", "", heading or "").strip()


def renumber_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    number = 1
    for section in sections:
        copied = dict(section)
        heading = str(copied.get("heading") or "")
        if re.match(r"^\d+\.\s*", heading):
            copied["heading"] = f"{number}. {strip_heading_number(heading)}"
            number += 1
        result.append(copied)
    return result


def build_agent_registry_rows(state: dict[str, Any]) -> list[list[Any]]:
    rows = []
    for agent in state.get("agent_registry", []) or state.get("agent_evaluation", {}).get("agent_registry", []):
        rows.append([
            agent.get("name", "-"),
            agent.get("implementation", "-"),
            ", ".join(agent.get("tools", [])) or "-",
            ", ".join(agent.get("controls", [])) or "-",
        ])
    return rows


def build_agent_decision_rows(state: dict[str, Any]) -> list[list[Any]]:
    rows = []
    for decision in state.get("agent_decisions", []) or []:
        if decision.get("phase") != "post_tool_observation":
            continue
        rows.append([
            decision.get("node_name", "-"),
            decision.get("selected_tool", "-"),
            decision.get("decision", "-"),
            "Y" if decision.get("changed_output") else "N",
            decision.get("reason", "-"),
        ])
    return rows


def build_agent_evaluation_rows(state: dict[str, Any]) -> list[list[Any]]:
    rows = []
    for item in state.get("agent_evaluation", {}).get("items", []):
        critic = item.get("llm_critic") or {}
        rows.append([
            item.get("candidate_agent_name", "-"),
            percent(item.get("confidence_score", 0)),
            percent(item.get("critic_adjusted_confidence_score", item.get("confidence_score", 0))),
            percent(item.get("evidence_coverage", 0)),
            percent(item.get("data_confidence", 0)),
            percent(item.get("rationale_coverage", 0)),
            percent(item.get("risk_uncertainty", 0)),
            critic.get("critic_verdict", "-"),
            "Y" if item.get("requires_human_review") else "N",
            "Y" if item.get("requires_additional_evidence") else "N",
        ])
    return rows


def build_agent_evaluation_summary_rows(state: dict[str, Any]) -> list[list[Any]]:
    summary = state.get("agent_evaluation", {}).get("summary", {})
    rows = [
        ["평가 후보 수", summary.get("evaluated_candidates", 0)],
        ["평균 confidence", percent(summary.get("average_confidence_score", 0))],
        ["낮은 confidence 후보", summary.get("low_confidence_count", 0)],
        ["Human Review 필요 후보", summary.get("human_review_required_count", 0)],
        ["추가 근거 필요 후보", summary.get("additional_evidence_required_count", 0)],
        ["Agent 결정 적용", "Y" if summary.get("agent_decision_applied") else "N"],
        ["Agent 결정 조정 후보", summary.get("agent_decision_adjusted_count", 0)],
    ]
    if summary.get("llm_critic_applied"):
        rows.extend([
            ["LLM Critic 적용", "Y"],
            ["LLM Critic 검토 후보", summary.get("llm_critic_review_count", 0)],
            ["LLM Critic 재검토 필요 후보", summary.get("llm_critic_needs_review_count", 0)],
        ])
    return rows


def normalize_replan_item(item: Any, state: dict[str, Any]) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    process_id = int(item or 0)
    candidate = next(
        (
            row
            for row in (state.get("priority_ranking", {}) or {}).get("items", [])
            if int(row.get("process_id") or 0) == process_id
        ),
        {},
    )
    evaluation = next(
        (
            row
            for row in (state.get("agent_evaluation", {}) or {}).get("items", [])
            if int(row.get("process_id") or 0) == process_id
        ),
        {},
    )
    return {
        "process_id": process_id,
        "candidate_agent_name": candidate.get("candidate_agent_name") or evaluation.get("candidate_agent_name") or f"process:{process_id}",
        "confidence_score": evaluation.get("confidence_score", 0),
        "evidence_coverage": evaluation.get("evidence_coverage", 0),
        "suggested_actions": [
            "공식 URL 또는 내부 문서 추가 수집",
            "업무 owner 인터뷰 메모 추가",
            "RAG 재색인 후 재평가",
        ],
    }


def build_replan_rows(state: dict[str, Any]) -> list[list[Any]]:
    rows = []
    raw_items = state.get("replan_request", {}).get("items", [])
    for raw_item in raw_items:
        item = normalize_replan_item(raw_item, state)
        rows.append([
            item.get("candidate_agent_name", "-"),
            percent(item.get("confidence_score", 0)),
            percent(item.get("evidence_coverage", 0)),
            ", ".join(str(value) for value in item.get("suggested_actions", [])[:3]),
        ])
    return rows


def build_agent_evaluation_section(state: dict[str, Any]) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = [
        {
            "type": "paragraph",
            "text": (
                "Agent Evaluator는 우선순위 산정 이후 후보별 evidence coverage, data confidence, "
                "점수 근거 coverage, compliance alignment, risk uncertainty를 재검증한다. "
                "LLM Critic은 가능한 경우 second-opinion 검토를 수행하고, 실패 시 deterministic fallback을 사용한다. "
                "confidence가 낮거나 규제·근거 정합성이 부족한 후보는 recommended 상태를 유지하지 않고 Human Review 또는 추가 근거 수집 대상으로 전환한다."
            ),
        },
        {
            "type": "table",
            "headers": ["항목", "결과"],
            "rows": build_agent_evaluation_summary_rows(state),
            "font_size": 8,
        },
        {
            "type": "table",
            "headers": ["후보 Agent", "Confidence", "Critic Adjusted", "Evidence", "Data", "Rationale", "Risk Uncertainty", "Critic", "Human Review", "추가 근거"],
            "rows": build_agent_evaluation_rows(state),
            "font_size": 6,
        },
    ]

    decision_rows = build_agent_decision_rows(state)
    if decision_rows:
        blocks.extend([
            {
                "type": "paragraph",
                "text": "아래 표는 Agent가 tool 실행 결과를 관찰한 뒤 실제 state에 반영한 post-decision 기록이다.",
            },
            {
                "type": "table",
                "headers": ["Node", "Selected Tool", "Decision", "Changed", "Reason"],
                "rows": decision_rows,
                "font_size": 6,
            },
        ])

    replan_rows = build_replan_rows(state)
    if replan_rows:
        blocks.extend([
            {
                "type": "paragraph",
                "text": "Agent Replan Loop는 evidence coverage가 낮은 후보에 대해 설정된 제한 횟수 안에서 RAG 문서와 공식 URL을 재검색하고, 추가 공식 URL·내부 문서·업무 owner 인터뷰 메모 등 보완 입력을 Human Review에 요청한다.",
            },
            {
                "type": "table",
                "headers": ["후보 Agent", "Confidence", "Evidence", "보완 Action"],
                "rows": replan_rows,
                "font_size": 6,
            },
        ])

    blocks.extend([
        {
            "type": "paragraph",
            "text": "아래 표는 Supervisor Graph에 등록된 Agent별 역할, 허용 도구, 통제 조건을 요약한 것이다. 이를 통해 각 Agent의 목적과 권한 범위를 명시적으로 제한한다.",
        },
        {
            "type": "table",
            "headers": ["Agent", "구현 방식", "허용 도구", "통제 조건"],
            "rows": build_agent_registry_rows(state),
            "font_size": 6,
        },
    ])

    return {"heading": "8. Agent Evaluation 및 신뢰도 검증", "blocks": blocks}


def insert_agent_evaluation_section(report_data: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    if not state.get("agent_evaluation"):
        return report_data

    sections = list(report_data.get("sections", []))
    if any("Agent Evaluation" in str(section.get("heading")) for section in sections):
        return report_data

    insert_index = None
    for idx, section in enumerate(sections):
        heading = str(section.get("heading") or "")
        if "PoC 실행계획" in heading:
            insert_index = idx
            break

    section = build_agent_evaluation_section(state)
    if insert_index is None:
        sections.append(section)
    else:
        sections.insert(insert_index, section)

    report_data = dict(report_data)
    report_data["sections"] = renumber_sections(sections)
    report_data["agent_evaluation"] = state.get("agent_evaluation", {})
    report_data["agent_registry"] = state.get("agent_registry", [])
    report_data["agent_decisions"] = state.get("agent_decisions", [])
    report_data["replan_request"] = state.get("replan_request", {})
    return report_data


def build_report_data(state: dict[str, Any]) -> dict[str, Any]:
    """
    Public report builder entrypoint used by graph nodes.

    Flow:
    1. Try vLLM/Gemma Report Writer Agent.
    2. If vLLM is unavailable, JSON parsing fails, or citation validation fails,
       the chain returns the deterministic fallback report.
    3. Append Agent Evaluator/Critic section when available.
    """
    report_data = generate_report_data_with_llm(state)
    return insert_agent_evaluation_section(report_data, state)
