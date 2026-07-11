# app/chains/report_writer.py

"""분석 결과를 보고서 문장/section 구조로 변환하는 chain.

RAG evidence, ranking, PoC 계획, governance 결과를 바탕으로 citation을 포함한
보고서 데이터를 생성하고, 실패 시 deterministic report builder로 fallback한다.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any

from langchain_core.prompts import ChatPromptTemplate

from app.agents.model_router import compact_model_assignment, select_agent_model
from app.core.llm import get_chat_model, invoke_chat_with_retry
from app.tools.citation_validator import find_citation_labels, validate_report_citations
from app.tools.deterministic_report_data_builder import build_report_data as build_deterministic_report_data


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
6. 기업 및 산업 특성 분석 장에서는 웹페이지 원문, 메뉴명, 팝업, 제품 프로모션 문구, 검색창/장바구니/카테고리 텍스트를 절대 재현하지 않는다.
7. 기업 및 산업 특성 분석 장은 기업 식별 정보, 산업 구분, AX 해석 포인트만 2~3문장으로 간결하게 쓴다.
8. 모든 paragraph 끝에는 가능한 한 allowed citation label을 1개 이상 포함한다.
"""

USER_PROMPT = """
아래 base_sections의 paragraph만 더 자연스러운 보고서 문체로 재작성하라.
표, 순위, 수치, citation label은 제공된 근거와 tool output에 있는 것만 사용하라.
특히 "2. 기업 및 산업 특성 분석"은 raw web text를 요약하지 말고 base section의 의도만 간결하게 유지하라.
각 paragraph는 일반적인 방법론 문장이 아닌 한 문장 끝에 allowed citation label을 붙여라.

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

NOISE_PATTERNS = [
    "본문 바로가기",
    "일주일 그만보기",
    "장바구니",
    "검색창",
    "검색결과",
    "최근 본 제품",
    "전체삭제",
    "닫기",
    "신청하기",
    "카테고리",
    "메뉴버튼",
    "검색버튼",
]

CITATION_EXEMPT_PATTERNS = [
    "본 보고서는",
    "본 문서는",
    "아래 표는",
    "다음 표는",
]


def compact_json(value: Any, max_chars: int = 12000) -> str:
    """compact_json 함수. 분석 결과를 보고서 문장/section 구조로 변환하는 chain. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= max_chars else text[:max_chars] + "..."


def clean_evidence_summary(text: str, max_chars: int = 500) -> str:
    """clean_evidence_summary 함수. 분석 결과를 보고서 문장/section 구조로 변환하는 chain. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    cleaned_lines = []
    for line in str(text or "").splitlines():
        cleaned = " ".join(line.split()).strip()
        if not cleaned:
            continue
        if any(pattern in cleaned for pattern in NOISE_PATTERNS):
            continue
        if len(cleaned) < 8:
            continue
        cleaned_lines.append(cleaned)
        if len(" ".join(cleaned_lines)) >= max_chars:
            break
    result = " ".join(cleaned_lines)
    return result[:max_chars]


def extract_json_object(text: str) -> dict[str, Any]:
    """extract_json_object 함수. 분석 결과를 보고서 문장/section 구조로 변환하는 chain. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
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


def append_unique(labels: list[str], label: str | None) -> None:
    """append_unique 함수. 분석 결과를 보고서 문장/section 구조로 변환하는 chain. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    if label and label not in labels:
        labels.append(str(label))


def build_allowed_citation_labels(evidence_items: list[dict[str, Any]], state: dict[str, Any] | None = None) -> list[str]:
    """build_allowed_citation_labels 함수. 입력 state나 domain 객체를 조합해 downstream에서 사용할 구조화된 payload를 만든다."""
    labels: list[str] = []

    for item in evidence_items:
        append_unique(labels, item.get("citation_label"))

    state = state or {}
    for candidate in state.get("priority_ranking", {}).get("items", []):
        metadata = candidate.get("discovery_metadata") or {}
        for label in metadata.get("evidence_labels", []):
            append_unique(labels, str(label))

        for text in [candidate.get("problem"), candidate.get("reason"), candidate.get("suitability_rationale")]:
            for label in find_citation_labels(str(text or "")):
                append_unique(labels, label)

        for text in (candidate.get("score_rationale") or {}).values():
            for label in find_citation_labels(str(text or "")):
                append_unique(labels, label)

    return labels


def build_evidence_context(evidence_items: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    """build_evidence_context 함수. 입력 state나 domain 객체를 조합해 downstream에서 사용할 구조화된 payload를 만든다."""
    sorted_items = sorted(evidence_items, key=lambda item: float(item.get("confidence") or 0.0), reverse=True)
    context = []

    for item in sorted_items[:limit]:
        raw_summary = item.get("summary") or item.get("content", "")
        context.append(
            {
                "citation_label": item.get("citation_label"),
                "source_type": item.get("source_type"),
                "title": item.get("title"),
                "summary": clean_evidence_summary(str(raw_summary), max_chars=500),
                "used_for": item.get("used_for", []),
                "process_id": item.get("process_id"),
                "confidence": item.get("confidence"),
            }
        )
    return context


def build_base_sections_payload(report_data: dict[str, Any]) -> list[dict[str, Any]]:
    """build_base_sections_payload 함수. 입력 state나 domain 객체를 조합해 downstream에서 사용할 구조화된 payload를 만든다."""
    payload = []
    for section in report_data.get("sections", []):
        paragraphs = []
        table_summaries = []
        for block in section.get("blocks", []):
            if block.get("type") == "paragraph":
                paragraphs.append(block.get("text", ""))
            elif block.get("type") == "table":
                table_summaries.append({"headers": block.get("headers", []), "row_count": len(block.get("rows", []))})
        payload.append({"heading": section.get("heading"), "paragraphs": paragraphs, "tables": table_summaries})
    return payload


def build_analysis_summary(state: dict[str, Any]) -> dict[str, Any]:
    """build_analysis_summary 함수. 입력 state나 domain 객체를 조합해 downstream에서 사용할 구조화된 payload를 만든다."""
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


def should_skip_citation_enforcement(text: str) -> bool:
    """should_skip_citation_enforcement 함수. 분석 결과를 보고서 문장/section 구조로 변환하는 chain. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    stripped = str(text or "").strip()
    if not stripped:
        return True
    if len(stripped) < 40:
        return True
    return any(stripped.startswith(pattern) for pattern in CITATION_EXEMPT_PATTERNS)


def select_default_citation_label(allowed_labels: list[str], evidence_items: list[dict[str, Any]]) -> str | None:
    """select_default_citation_label 함수. 여러 후보 중 workflow 정책에 맞는 항목을 선택한다."""
    if evidence_items:
        sorted_items = sorted(evidence_items, key=lambda item: float(item.get("confidence") or 0.0), reverse=True)
        for item in sorted_items:
            label = item.get("citation_label")
            if label in allowed_labels:
                return str(label)
    return allowed_labels[0] if allowed_labels else None


def enforce_citation_coverage(report_data: dict[str, Any], allowed_labels: list[str], evidence_items: list[dict[str, Any]]) -> dict[str, Any]:
    """enforce_citation_coverage 함수. 분석 결과를 보고서 문장/section 구조로 변환하는 chain. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    default_label = select_default_citation_label(allowed_labels, evidence_items)
    if not default_label:
        return report_data

    report_data = deepcopy(report_data)
    appended_count = 0
    for section in report_data.get("sections", []):
        for block in section.get("blocks", []):
            if block.get("type") != "paragraph":
                continue
            text = str(block.get("text") or "")
            if should_skip_citation_enforcement(text):
                continue
            if find_citation_labels(text):
                continue
            block["text"] = f"{text.rstrip()} {default_label}"
            appended_count += 1

    generation = dict(report_data.get("generation") or {})
    warnings = list(generation.get("warnings") or [])
    if appended_count:
        warnings.append(f"citation coverage post-process appended default labels to {appended_count} paragraph(s).")
    generation["warnings"] = warnings
    report_data["generation"] = generation
    return report_data


def apply_llm_paragraphs(base_report_data: dict[str, Any], llm_payload: dict[str, Any]) -> dict[str, Any]:
    """apply_llm_paragraphs 함수. 계산된 결정이나 검토 결과를 기존 payload에 반영한다."""
    report_data = deepcopy(base_report_data)
    llm_sections = llm_payload.get("sections", [])
    section_map = {item.get("heading"): item.get("paragraphs", []) for item in llm_sections if item.get("heading")}

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

    report_data["generation"] = {"mode": "routed_report_writer", "warnings": llm_payload.get("warnings", [])}
    return report_data


def build_fallback_report_data(
    state: dict[str, Any],
    reason: str,
    model_assignment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """build_fallback_report_data 함수. 입력 state나 domain 객체를 조합해 downstream에서 사용할 구조화된 payload를 만든다."""
    report_data = build_deterministic_report_data(state)
    report_data["generation"] = {
        "mode": "deterministic_fallback",
        "reason": reason,
        "model_selection": compact_model_assignment(model_assignment),
    }
    return report_data


def generate_report_data_with_llm(state: dict[str, Any]) -> dict[str, Any]:
    """generate_report_data_with_llm 함수. 분석 결과를 보고서 문장/section 구조로 변환하는 chain. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    base_report_data = build_deterministic_report_data(state)
    evidence_items = state.get("evidence_items", [])
    allowed_citation_labels = build_allowed_citation_labels(evidence_items, state=state)

    # Report Writer는 출력량이 크고 citation 품질이 중요하므로 별도 call_kind로
    # 모델을 다시 선택한다. 이 선택 결과는 보고서 metadata와 graph trace에 남는다.
    model_assignment = select_agent_model(
        agent_id="delivery_orchestration_agent",
        stage_name="report_writer",
        call_kind="report_writer",
        state=state,
    )

    if not evidence_items or not allowed_citation_labels:
        return build_fallback_report_data(
            state,
            reason="No evidence items or citation labels are available.",
            model_assignment=model_assignment,
        )

    prompt = ChatPromptTemplate.from_messages([("system", SYSTEM_PROMPT), ("human", USER_PROMPT)])

    try:
        llm = get_chat_model(temperature=0.2, model_assignment=model_assignment)
        messages = prompt.format_messages(
            allowed_citation_labels=compact_json(allowed_citation_labels, max_chars=3000),
            company_profile=compact_json(state.get("company_profile", {}), max_chars=1200),
            analysis_summary=compact_json(build_analysis_summary(state), max_chars=7000),
            evidence_context=compact_json(build_evidence_context(evidence_items), max_chars=7000),
            base_sections=compact_json(build_base_sections_payload(base_report_data), max_chars=12000),
        )

        response = invoke_chat_with_retry(llm, messages)
        llm_payload = extract_json_object(str(response.content))
        report_data = apply_llm_paragraphs(base_report_data, llm_payload)
        report_data["generation"]["provider"] = model_assignment.get("provider")
        report_data["generation"]["model"] = model_assignment.get("model")
        report_data["generation"]["model_selection"] = compact_model_assignment(model_assignment)
        report_data = enforce_citation_coverage(report_data, allowed_citation_labels, evidence_items)

        validation = validate_report_citations(report_data=report_data, evidence_items=evidence_items)
        report_data["citation_validation"] = validation

        if not validation.get("valid"):
            return build_fallback_report_data(
                state,
                reason=f"Invalid citation labels from LLM: {validation.get('invalid_labels')}",
                model_assignment=model_assignment,
            )

        return report_data

    except Exception as exc:
        return build_fallback_report_data(
            state,
            reason=f"LLM report writer failed: {type(exc).__name__}: {exc}",
            model_assignment=model_assignment,
        )
