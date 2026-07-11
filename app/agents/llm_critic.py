# app/agents/llm_critic.py

"""LLM 기반 2차 비평자 역할을 수행한다.

deterministic evaluator가 만든 평가 결과를 입력으로 받아, 근거 부족/과도한 추천/
컴플라이언스 불일치 가능성을 한 번 더 점검한다. LLM 실패 시에도 deterministic
평가 결과를 유지하도록 fallback 구조를 둔다.
"""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.prompts import ChatPromptTemplate

from app.agents.evaluation_policy import deterministic_critic_verdict, normalize_critic_verdict
from app.agents.model_router import compact_model_assignment
from app.core.llm import get_chat_model, invoke_chat_with_retry

SYSTEM_PROMPT = """
You are a calibrated AX Agent Critic.
You review candidate AI Agent recommendations using only the provided JSON.
Do not add external facts. Return JSON only.

Be conservative for blocked, sensitive, high-impact, or weak-evidence candidates.
Do not mark every candidate as needs_review. If the deterministic evaluation is strong,
there are no compliance issues, and confidence is adequate, return pass.
""".strip()

USER_PROMPT = """
Review the candidate recommendation and deterministic evaluation.

Candidate:
{candidate}

Evaluation:
{evaluation}

Guidance:
- Return pass when confidence_score >= 0.70, requires_additional_evidence=false, compliance_alignment is high, and issues is empty.
- Return needs_replan when evidence is moderate but below the additional-evidence threshold and automatic source collection can improve it.
- Return needs_review for sensitive_review, enhanced_review, unclear reviewer responsibility, or moderate uncertainty.
- Return insufficient_evidence only when evidence_coverage is zero/very weak or the candidate should not be shown as a recommendation before replan.
- Return reject only for blocked/prohibited use or clearly unsafe scope.

Return JSON:
{{
  "critic_verdict": "pass|needs_replan|needs_review|insufficient_evidence|reject",
  "critic_confidence_adjustment": -0.10,
  "critic_reason": "short Korean reason",
  "missing_evidence": ["item"],
  "review_questions": ["question"]
}}
""".strip()


def compact_json(value: Any, max_chars: int = 5000) -> str:
    """compact_json 함수. LLM 기반 2차 비평자 역할을 수행한다. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= max_chars else text[:max_chars] + "..."


def extract_json_object(text: str) -> dict[str, Any]:
    """extract_json_object 함수. LLM 기반 2차 비평자 역할을 수행한다. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def normalize_verdict(value: Any) -> str:
    """normalize_verdict 함수. 비교/저장/출력을 안정화하기 위해 입력값 형식을 정규화한다."""
    return normalize_critic_verdict(value)


def clamp_adjustment(value: Any) -> float:
    """clamp_adjustment 함수. LLM 기반 2차 비평자 역할을 수행한다. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return round(max(-0.30, min(0.10, parsed)), 3)


def deterministic_verdict(candidate: dict[str, Any], evaluation: dict[str, Any]) -> str:
    """deterministic_verdict 함수. LLM 기반 2차 비평자 역할을 수행한다. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    return deterministic_critic_verdict(candidate, evaluation)


def calibrate_critic_verdict(candidate: dict[str, Any], evaluation: dict[str, Any], critic: dict[str, Any]) -> dict[str, Any]:
    """calibrate_critic_verdict 함수. LLM 기반 2차 비평자 역할을 수행한다. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    expected = deterministic_verdict(candidate, evaluation)
    verdict = normalize_verdict(critic.get("critic_verdict"))

    if expected == "pass" and verdict in {"needs_replan", "needs_review", "insufficient_evidence"}:
        critic = dict(critic)
        critic["critic_verdict"] = "pass"
        critic["critic_confidence_adjustment"] = max(0.0, float(critic.get("critic_confidence_adjustment") or 0.0))
        critic["critic_reason"] = "정량 평가상 근거·정합성 기준을 충족하여 LLM Critic의 과도한 재검토 판정을 pass로 보정했다."
        critic["missing_evidence"] = []
        critic["review_questions"] = []
        critic["critic_calibrated"] = True
        return critic

    if expected == "needs_replan" and verdict == "insufficient_evidence":
        critic = dict(critic)
        critic["critic_verdict"] = "needs_replan"
        critic["critic_confidence_adjustment"] = min(0.0, float(critic.get("critic_confidence_adjustment") or 0.0))
        critic["critic_reason"] = "근거가 부족하지만 심각한 결측은 아니므로 Human Review 전에 자동 replan으로 근거 보강을 우선하도록 보정했다."
        critic["critic_calibrated"] = True
        return critic

    critic = dict(critic)
    critic["critic_verdict"] = verdict
    critic["critic_calibrated"] = False
    return critic


def fallback_critic(
    candidate: dict[str, Any],
    evaluation: dict[str, Any],
    reason: str,
    model_assignment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """fallback_critic 함수. LLM 기반 2차 비평자 역할을 수행한다. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    verdict = deterministic_verdict(candidate, evaluation)
    adjustment = -0.05 if verdict == "insufficient_evidence" else (-0.03 if verdict == "needs_replan" else 0.0)
    return {
        "critic_verdict": verdict,
        "critic_confidence_adjustment": adjustment,
        "critic_reason": f"LLM Critic 사용 불가로 deterministic 평가 기준을 적용했다. {reason}",
        "missing_evidence": evaluation.get("issues", []) if verdict != "pass" else [],
        "review_questions": [],
        "critic_mode": "deterministic_fallback",
        "critic_calibrated": False,
        "model_selection": compact_model_assignment(model_assignment),
    }


def run_llm_critic(
    candidate: dict[str, Any],
    evaluation: dict[str, Any],
    model_assignment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """run_llm_critic 함수. 외부 API, graph, worker, 평가 루틴 같은 실행 단위를 호출하고 결과를 반환한다."""
    try:
        prompt = ChatPromptTemplate.from_messages([("system", SYSTEM_PROMPT), ("human", USER_PROMPT)])
        # LLM Critic은 Evaluation Agent 내부 도구지만 실제 모델은
        # Supervisor 라우터가 계산한 가격 대비 효율 결과를 따른다.
        llm = get_chat_model(temperature=0.0, model_assignment=model_assignment)
        messages = prompt.format_messages(
            candidate=compact_json(candidate),
            evaluation=compact_json(evaluation),
        )
        response = invoke_chat_with_retry(llm, messages)
        payload = extract_json_object(str(response.content))
        critic = {
            "critic_verdict": normalize_verdict(payload.get("critic_verdict")),
            "critic_confidence_adjustment": clamp_adjustment(payload.get("critic_confidence_adjustment")),
            "critic_reason": str(payload.get("critic_reason") or "LLM Critic 검토 완료."),
            "missing_evidence": payload.get("missing_evidence") if isinstance(payload.get("missing_evidence"), list) else [],
            "review_questions": payload.get("review_questions") if isinstance(payload.get("review_questions"), list) else [],
            "critic_mode": "llm_critic",
            "model_selection": compact_model_assignment(model_assignment),
        }
        return calibrate_critic_verdict(candidate, evaluation, critic)
    except Exception as exc:
        return fallback_critic(candidate, evaluation, f"{type(exc).__name__}: {exc}", model_assignment=model_assignment)


def apply_llm_critic_to_evaluation(
    priority_ranking: dict[str, Any],
    agent_evaluation: dict[str, Any],
    model_assignment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """apply_llm_critic_to_evaluation 함수. 계산된 결정이나 검토 결과를 기존 payload에 반영한다."""
    evaluation_map = {
        int(item.get("process_id") or 0): dict(item)
        for item in agent_evaluation.get("items", [])
        if item.get("process_id") is not None
    }

    updated_items = []
    for candidate in priority_ranking.get("items", []):
        process_id = int(candidate.get("process_id") or 0)
        evaluation = evaluation_map.get(process_id)
        if not evaluation:
            updated_items.append(candidate)
            continue

        critic = run_llm_critic(candidate, evaluation, model_assignment=model_assignment)
        adjusted_confidence = round(
            max(0.0, min(1.0, float(evaluation.get("confidence_score") or 0.0) + float(critic.get("critic_confidence_adjustment") or 0.0))),
            3,
        )
        evaluation["llm_critic"] = critic
        evaluation["critic_adjusted_confidence_score"] = adjusted_confidence

        copied = dict(candidate)
        copied["agent_evaluation"] = evaluation
        critic_verdict = str(critic.get("critic_verdict") or "")
        if critic_verdict in {"reject", "insufficient_evidence"} and copied.get("status") == "recommended":
            copied["status"] = "evidence_insufficient"
            copied["reason"] = f"{copied.get('reason', '')} LLM Critic 검토 결과 추가 근거가 필요하다.".strip()
        elif critic_verdict == "needs_review" and copied.get("status") == "recommended":
            copied["status"] = "human_review_required"
            copied["reason"] = f"{copied.get('reason', '')} LLM Critic 검토 결과 Human Review가 필요하다.".strip()
        elif critic_verdict == "needs_replan":
            copied["agent_decision_status"] = "auto_replan_required"
            copied["agent_decision_reason"] = "LLM Critic은 Human Review 전에 자동 근거 보강을 우선해야 한다고 판단했다."
        updated_items.append(copied)
        evaluation_map[process_id] = evaluation

    updated_ranking = dict(priority_ranking)
    updated_ranking["items"] = updated_items
    updated_evaluation = dict(agent_evaluation)
    updated_evaluation["items"] = list(evaluation_map.values())
    updated_evaluation["summary"] = {
        **(agent_evaluation.get("summary") or {}),
        "llm_critic_applied": True,
        "llm_critic_review_count": len(evaluation_map),
        "llm_critic_needs_review_count": sum(
            1 for item in evaluation_map.values()
            if (item.get("llm_critic") or {}).get("critic_verdict") in {"needs_review", "insufficient_evidence", "reject"}
        ),
        "llm_critic_needs_replan_count": sum(
            1 for item in evaluation_map.values()
            if (item.get("llm_critic") or {}).get("critic_verdict") == "needs_replan"
        ),
        "llm_critic_calibrated_count": sum(
            1 for item in evaluation_map.values()
            if (item.get("llm_critic") or {}).get("critic_calibrated")
        ),
    }
    return {"priority_ranking": updated_ranking, "agent_evaluation": updated_evaluation}
