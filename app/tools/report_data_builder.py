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


def build_agent_evaluation_rows(state: dict[str, Any]) -> list[list[Any]]:
    rows = []
    for item in state.get("agent_evaluation", {}).get("items", []):
        rows.append([
            item.get("candidate_agent_name", "-"),
            percent(item.get("confidence_score", 0)),
            percent(item.get("evidence_coverage", 0)),
            percent(item.get("data_confidence", 0)),
            percent(item.get("rationale_coverage", 0)),
            percent(item.get("risk_uncertainty", 0)),
            "Y" if item.get("requires_human_review") else "N",
            "Y" if item.get("requires_additional_evidence") else "N",
        ])
    return rows


def build_agent_evaluation_summary_rows(state: dict[str, Any]) -> list[list[Any]]:
    summary = state.get("agent_evaluation", {}).get("summary", {})
    return [
        ["평가 후보 수", summary.get("evaluated_candidates", 0)],
        ["평균 confidence", percent(summary.get("average_confidence_score", 0))],
        ["낮은 confidence 후보", summary.get("low_confidence_count", 0)],
        ["Human Review 필요 후보", summary.get("human_review_required_count", 0)],
        ["추가 근거 필요 후보", summary.get("additional_evidence_required_count", 0)],
    ]


def build_agent_evaluation_section(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "heading": "8. Agent Evaluation 및 신뢰도 검증",
        "blocks": [
            {
                "type": "paragraph",
                "text": (
                    "Agent Evaluator는 우선순위 산정 이후 후보별 evidence coverage, data confidence, "
                    "점수 근거 coverage, compliance alignment, risk uncertainty를 재검증한다. "
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
                "headers": ["후보 Agent", "Confidence", "Evidence", "Data", "Rationale", "Risk Uncertainty", "Human Review", "추가 근거"],
                "rows": build_agent_evaluation_rows(state),
                "font_size": 6,
            },
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
        ],
    }


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
