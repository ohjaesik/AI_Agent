# app/chains/company_process_discovery.py

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.prompts import ChatPromptTemplate

from app.agents.model_router import compact_model_assignment, select_agent_model
from app.core.llm import get_chat_model, invoke_chat_with_retry

ALLOWED_DEPARTMENTS = {
    "AX전략/기획",
    "IT/데이터",
    "운영/생산",
    "영업/고객",
    "경영지원",
}

SYSTEM_PROMPT = """
You are a Company Process Discovery Agent for AX transformation consulting.

Your task is to read only the provided official company sources and create company-specific candidate business processes for AI Agent adoption.

Rules:
- Use only the provided source texts.
- Do not invent business areas, products, operations, systems, or numbers not supported by sources.
- Every process must include at least one evidence label from the allowed labels.
- Prefer company-specific candidates over generic candidates.
- Do not create candidates that are merely generic office automation unless the sources support them.
- Return JSON only. No markdown.
- Department must be one of: AX전략/기획, IT/데이터, 운영/생산, 영업/고객, 경영지원.
- Scores must be integers from 1 to 5.
""".strip()

USER_PROMPT = """
Company name: {company_name}

Allowed evidence labels:
{allowed_labels}

Official source excerpts:
{source_context}

Create 5 to 8 company-specific AX candidate business processes.

Return this exact JSON shape:
{{
  "processes": [
    {{
      "department": "운영/생산",
      "name": "업무명",
      "target_user": "대상 사용자",
      "problem": "공식자료 근거가 반영된 문제 정의 [EVIDENCE-LABEL]",
      "current_workflow": "현재 수작업/반복 업무 흐름 추정. 반드시 공식자료 근거 label 포함 [EVIDENCE-LABEL]",
      "candidate_agent_name": "후보 Agent명",
      "weekly_hours": 8.0,
      "expected_effect": 4,
      "repeatability": 4,
      "document_dependency": 4,
      "decision_complexity": 3,
      "data_accessibility": 3,
      "tech_feasibility": 4,
      "user_acceptance": 4,
      "risk_score": 3,
      "implementation_cost_score": 3,
      "suitability_rationale": "왜 이 업무가 AX/AI Agent 전환 후보로 적합한지 공식자료 근거와 연결해 설명 [EVIDENCE-LABEL]",
      "score_rationale": {{
        "expected_effect": "기대효과 점수 이유 [EVIDENCE-LABEL]",
        "repeatability": "반복성 점수 이유 [EVIDENCE-LABEL]",
        "document_dependency": "문서/지식 의존도 점수 이유 [EVIDENCE-LABEL]",
        "data_accessibility": "데이터 접근성 점수 이유 [EVIDENCE-LABEL]",
        "tech_feasibility": "구현 가능성 점수 이유 [EVIDENCE-LABEL]",
        "risk_score": "위험도 점수 이유 [EVIDENCE-LABEL]"
      }},
      "evidence_labels": ["[EVIDENCE-LABEL]"]
    }}
  ],
  "warnings": []
}}
""".strip()


def extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or end <= start:
        raise ValueError("LLM output does not contain a JSON object.")

    return json.loads(text[start : end + 1])


def clamp_int(value: Any, default: int = 3, minimum: int = 1, maximum: int = 5) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default

    return max(minimum, min(parsed, maximum))


def safe_float(value: Any, default: float = 6.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default

    return max(1.0, min(parsed, 40.0))


def compact(text: str, max_chars: int = 3500) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[:max_chars] + "..."


def build_source_context(sources: list[dict[str, Any]]) -> str:
    blocks = []

    for source in sources:
        label = source.get("label")
        title = source.get("title")
        source_type = source.get("source_type")
        url = source.get("url")
        content = compact(str(source.get("content") or ""))
        blocks.append(
            "\n".join(
                [
                    f"Label: {label}",
                    f"Type: {source_type}",
                    f"Title: {title}",
                    f"URL: {url or ''}",
                    f"Content: {content}",
                ]
            )
        )

    return "\n\n---\n\n".join(blocks)


def normalize_department(value: Any) -> str:
    department = str(value or "").strip()
    return department if department in ALLOWED_DEPARTMENTS else "AX전략/기획"


def ensure_evidence_label(text: str, labels: list[str]) -> str:
    if any(label in text for label in labels):
        return text

    if labels:
        return f"{text} {labels[0]}".strip()

    return text


def build_score_rationale(raw: dict[str, Any], evidence_labels: list[str]) -> dict[str, str]:
    default_label = evidence_labels[0] if evidence_labels else ""
    raw_rationale = raw.get("score_rationale") or {}
    if not isinstance(raw_rationale, dict):
        raw_rationale = {}

    keys = [
        "expected_effect",
        "repeatability",
        "document_dependency",
        "data_accessibility",
        "tech_feasibility",
        "risk_score",
    ]

    result: dict[str, str] = {}

    for key in keys:
        text = str(raw_rationale.get(key) or "").strip()
        if not text:
            text = f"{key} 점수는 공식자료에서 확인되는 업무 특성과 AX 적용 가능성을 기준으로 산정했다."
        result[key] = ensure_evidence_label(text, [default_label] if default_label else evidence_labels)

    return result


def validate_processes(payload: dict[str, Any], allowed_labels: list[str], fallback_processes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw_processes = payload.get("processes")

    if not isinstance(raw_processes, list):
        raise ValueError("LLM payload does not include processes list.")

    valid: list[dict[str, Any]] = []

    for raw in raw_processes:
        if not isinstance(raw, dict):
            continue

        evidence_labels = [str(label) for label in raw.get("evidence_labels", []) if str(label) in allowed_labels]

        if not evidence_labels and allowed_labels:
            evidence_labels = [allowed_labels[0]]

        name = str(raw.get("name") or "").strip()
        candidate_agent_name = str(raw.get("candidate_agent_name") or "").strip()
        problem = str(raw.get("problem") or "").strip()
        current_workflow = str(raw.get("current_workflow") or "").strip()
        suitability_rationale = str(raw.get("suitability_rationale") or "").strip()

        if not name or not candidate_agent_name or not problem:
            continue

        problem = ensure_evidence_label(problem, evidence_labels)
        current_workflow = ensure_evidence_label(current_workflow or problem, evidence_labels)
        suitability_rationale = ensure_evidence_label(
            suitability_rationale or "공식자료에서 확인되는 업무 특성과 반복적 판단·문서 활용 가능성을 고려할 때 AX 전환 후보로 볼 수 있다.",
            evidence_labels,
        )
        score_rationale = build_score_rationale(raw, evidence_labels)

        valid.append(
            {
                "department": normalize_department(raw.get("department")),
                "name": name[:100],
                "target_user": str(raw.get("target_user") or "현업 담당자").strip()[:100],
                "problem": problem,
                "current_workflow": current_workflow,
                "candidate_agent_name": candidate_agent_name[:150],
                "weekly_hours": safe_float(raw.get("weekly_hours"), default=6.0),
                "expected_effect": clamp_int(raw.get("expected_effect"), default=4),
                "repeatability": clamp_int(raw.get("repeatability"), default=4),
                "document_dependency": clamp_int(raw.get("document_dependency"), default=4),
                "decision_complexity": clamp_int(raw.get("decision_complexity"), default=3),
                "data_accessibility": clamp_int(raw.get("data_accessibility"), default=3),
                "tech_feasibility": clamp_int(raw.get("tech_feasibility"), default=4),
                "user_acceptance": clamp_int(raw.get("user_acceptance"), default=4),
                "risk_score": clamp_int(raw.get("risk_score"), default=3),
                "implementation_cost_score": clamp_int(raw.get("implementation_cost_score"), default=3),
                "evidence_labels": evidence_labels,
                "suitability_rationale": suitability_rationale,
                "score_rationale": score_rationale,
                "discovery_mode": "llm_company_process_discovery",
            }
        )

    if len(valid) < 3:
        raise ValueError("Too few valid LLM-discovered processes.")

    return valid[:8]


def add_fallback_metadata(processes: list[dict[str, Any]], reason: str) -> list[dict[str, Any]]:
    result = []

    for process in processes:
        copied = dict(process)
        copied["discovery_mode"] = "template_fallback"
        copied["discovery_warning"] = reason
        copied["suitability_rationale"] = "공식자료 기반 Discovery Agent 실패로 template 후보를 사용했다."
        copied["score_rationale"] = {
            "expected_effect": "template 기본 점수 사용",
            "repeatability": "template 기본 점수 사용",
            "document_dependency": "template 기본 점수 사용",
            "data_accessibility": "template 기본 점수 사용",
            "tech_feasibility": "template 기본 점수 사용",
            "risk_score": "template 기본 점수 사용",
        }
        result.append(copied)

    return result


def discover_company_process_specs(
    company_name: str,
    official_sources: list[dict[str, Any]],
    fallback_processes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    allowed_labels = [str(source.get("label")) for source in official_sources if source.get("label")]

    if not official_sources or not allowed_labels:
        return add_fallback_metadata(fallback_processes, "No official source labels are available.")

    # Process Discovery Agent는 공식자료의 양과 source 수에 따라 모델을 고른다.
    # bootstrap 단계에는 메인 graph state가 없으므로 필요한 값만 임시 state로
    # 구성해 동일한 Supervisor 라우팅 수식을 재사용한다.
    model_assignment = select_agent_model(
        agent_id="company_onboarding_agent",
        stage_name="process_discovery_agent",
        call_kind="process_discovery_llm",
        state={
            "official_sources": official_sources,
            "documents": official_sources,
            "business_processes": fallback_processes,
        },
    )

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            ("user", USER_PROMPT),
        ]
    )

    try:
        llm = get_chat_model(temperature=0.1, model_assignment=model_assignment)
        messages = prompt.format_messages(
            company_name=company_name,
            allowed_labels="\n".join(allowed_labels),
            source_context=build_source_context(official_sources),
        )
        response = invoke_chat_with_retry(llm, messages)
        payload = extract_json_object(str(response.content))
        processes = validate_processes(
            payload=payload,
            allowed_labels=allowed_labels,
            fallback_processes=fallback_processes,
        )
        for process in processes:
            process["discovery_model_selection"] = compact_model_assignment(model_assignment)
        return processes
    except Exception as exc:
        processes = add_fallback_metadata(
            fallback_processes,
            (
                f"LLM process discovery failed: {type(exc).__name__}: {exc} "
                f"(model={model_assignment.get('provider')}/{model_assignment.get('model')})"
            ),
        )
        for process in processes:
            process["discovery_model_selection"] = compact_model_assignment(model_assignment)
        return processes
