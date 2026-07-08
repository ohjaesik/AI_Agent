# app/chains/report_writer.py

from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any

from langchain_core.prompts import ChatPromptTemplate

from app.core.config import get_settings
from app.core.llm import get_chat_model
from app.tools.citation_validator import validate_report_citations
from app.tools.report_data_builder import build_report_data


SYSTEM_PROMPT = """
너는 제조기업 AX 전환 컨설팅 보고서를 작성하는 Report Writer Agent다.
반드시 제공된 evidence, tool output, base report draft 안의 정보만 사용한다.
새로운 외부 사실, 임의 참고문헌, 임의 수치, 임의 기업 사례를 만들면 안 된다.

규칙:
1. 모든 핵심 주장에는 allowed citation label 중 하나를 붙인다.
2. citation label은 새로 만들지 말고 제공된 label만 사용한다.
3. 표는 생성하지 않는다. 표는 기존 deterministic report의 표를 그대로 사용한다.
4. 반환은 JSON만 한다. markdown code fence를 쓰지 않는다.
5. 각 heading의 paragraphs 개수는 입력된 base_sections와 동일하게 유지한다.
"""

USER_PROMPT = """
아래 base_sections의 paragraph만 더 자연스러운 보고서 문체로 재작성하라.
표, 순위, 수치, citation label은 제공된 근거와 tool output에 있는 것만 사용하라.

allowed_citation_labels:
{allowed_citation_labels}

company_profile:
{company_profile}

analysis_summary:
{analysis_summary}

evidence_context:
{evidence_context}

base_sections:
{base_sections}

반환 JSON schema:
{{
  "sections": [
    {{
      "heading": "입력 heading과 동일",
      "paragraphs": ["재작성 paragraph 1", "재작성 paragraph 2"]
    }}
  ],
  "warnings": ["부족한 근거나 작성상 주의점"]
}}
"""


def compact_json(value: Any, max_chars: int = 12000) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)

    if len(text) <= max_chars:
        return text

    return text[:max_chars] + "..."


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()

    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError("LLM response does not contain a JSON object.")

    return json.loads(match.group(0))


def build_allowed_citation_labels(evidence_items: list[dict[str, Any]]) -> list[str]:
    labels: list[str] = []

    for item in evidence_items:
        label = item.get("citation_label")
        if label and label not in labels:
            labels.append(str(label))

    return labels


def build_evidence_context(
    evidence_items: list[dict[str, Any]],
    limit: int = 12,
) -> list[dict[str, Any]]:
    sorted_items = sorted(
        evidence_items,
        key=lambda item: float(item.get("confidence") or 0.0),
        reverse=True,
    )

    context = []

    for item in sorted_items[:limit]:
        context.append(
            {
                "citation_label": item.get("citation_label"),
                "source_type": item.get("source_type"),
                "title": item.get("title"),
                "summary": item.get("summary") or str(item.get("content", ""))[:500],
                "used_for": item.get("used_for", []),
                "process_id": item.get("process_id"),
                "confidence": item.get("confidence"),
            }
        )

    return context


def build_base_sections_payload(report_data: dict[str, Any]) -> list[dict[str, Any]]:
    payload = []

    for section in report_data.get("sections", []):
        paragraphs = []
        table_summaries = []

        for block in section.get("blocks", []):
            if block.get("type") == "paragraph":
                paragraphs.append(block.get("text", ""))
            elif block.get("type") == "table":
                table_summaries.append(
                    {
                        "headers": block.get("headers", []),
                        "row_count": len(block.get("rows", [])),
                    }
                )

        payload.append(
            {
                "heading": section.get("heading"),
                "paragraphs": paragraphs,
                "tables": table_summaries,
            }
        )

    return payload


def build_analysis_summary(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "process_analysis": state.get("process_analysis", {}).get("summary", {}),
        "data_readiness": state.get("data_readiness", {}).get("summary", {}),
        "automation_feasibility": state.get("automation_feasibility", {}).get("summary", {}),
        "roi_cost": state.get("roi_cost", {}).get("summary", {}),
        "risk_governance": state.get("risk_governance", {}).get("summary", {}),
        "priority_ranking": state.get("priority_ranking", {}).get("summary", {}),
        "poc_plan": state.get("poc_plan", {}),
        "human_review": state.get("human_review", {}),
    }


def apply_llm_paragraphs(
    base_report_data: dict[str, Any],
    llm_payload: dict[str, Any],
) -> dict[str, Any]:
    report_data = deepcopy(base_report_data)
    llm_sections = llm_payload.get("sections", [])
    section_map = {
        item.get("heading"): item.get("paragraphs", [])
        for item in llm_sections
        if item.get("heading")
    }

    for section in report_data.get("sections", []):
        heading = section.get("heading")
        rewritten_paragraphs = section_map.get(heading)

        if not rewritten_paragraphs:
            continue

        paragraph_index = 0

        for block in section.get("blocks", []):
            if block.get("type") != "paragraph":
                continue

            if paragraph_index >= len(rewritten_paragraphs):
                break

            block["text"] = rewritten_paragraphs[paragraph_index]
            paragraph_index += 1

    report_data["generation"] = {
        "mode": "vllm_report_writer",
        "warnings": llm_payload.get("warnings", []),
    }

    return report_data


def build_fallback_report_data(
    state: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    report_data = build_report_data(state)
    report_data["generation"] = {
        "mode": "deterministic_fallback",
        "reason": reason,
    }
    return report_data


def generate_report_data_with_llm(state: dict[str, Any]) -> dict[str, Any]:
    base_report_data = build_report_data(state)
    evidence_items = state.get("evidence_items", [])
    allowed_citation_labels = build_allowed_citation_labels(evidence_items)

    if not evidence_items or not allowed_citation_labels:
        return build_fallback_report_data(
            state,
            reason="No evidence items or citation labels are available.",
        )

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            ("human", USER_PROMPT),
        ]
    )

    settings = get_settings()

    try:
        llm = get_chat_model(temperature=0.2)
        messages = prompt.format_messages(
            allowed_citation_labels=compact_json(allowed_citation_labels, max_chars=3000),
            company_profile=compact_json(state.get("company_profile", {}), max_chars=2000),
            analysis_summary=compact_json(build_analysis_summary(state), max_chars=7000),
            evidence_context=compact_json(build_evidence_context(evidence_items), max_chars=10000),
            base_sections=compact_json(build_base_sections_payload(base_report_data), max_chars=12000),
        )

        response = llm.invoke(messages)
        llm_payload = extract_json_object(str(response.content))
        report_data = apply_llm_paragraphs(base_report_data, llm_payload)
        report_data["generation"]["model"] = settings.vllm_model

        validation = validate_report_citations(
            report_data=report_data,
            evidence_items=evidence_items,
        )
        report_data["citation_validation"] = validation

        if not validation.get("valid"):
            return build_fallback_report_data(
                state,
                reason=f"Invalid citation labels from LLM: {validation.get('invalid_labels')}",
            )

        return report_data

    except Exception as exc:
        return build_fallback_report_data(
            state,
            reason=f"LLM report writer failed: {type(exc).__name__}: {exc}",
        )
