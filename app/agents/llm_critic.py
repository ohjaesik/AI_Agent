# app/agents/llm_critic.py

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.prompts import ChatPromptTemplate

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
- Return needs_review for sensitive_review, enhanced_review, unclear reviewer responsibility, or moderate uncertainty.
- Return insufficient_evidence when evidence_coverage is weak or requires_additional_evidence=true.
- Return reject only for blocked/prohibited use or clearly unsafe scope.

Return JSON:
{{
  "critic_verdict": "pass|needs_review|insufficient_evidence|reject",
  "critic_confidence_adjustment": -0.10,
  "critic_reason": "short Korean reason",
  "missing_evidence": ["item"],
  "review_questions": ["question"]
}}
""".strip()


def compact_json(value: Any, max_chars: int = 5000) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= max_chars else text[:max_chars] + "..."


def extract_json_object(text: str) -> dict[str, Any]:
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
    verdict = str(value or "needs_review").strip().lower()
    return verdict if verdict in {"pass", "needs_review", "insufficient_evidence", "reject"} else "needs_review"


def clamp_adjustment(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return round(max(-0.30, min(0.10, parsed)), 3)


def deterministic_verdict(candidate: dict[str, Any], evaluation: dict[str, Any]) -> str:
    compliance = candidate.get("compliance") or {}
    if compliance.get("blocked"):
        return "reject"
    if evaluation.get("requires_additional_evidence"):
        return "insufficient_evidence"
    if compliance.get("compliance_level") in {"sensitive_review", "enhanced_review"}:
        return "needs_review"
    if evaluation.get("issues"):
        return "needs_review"
    if float(evaluation.get("confidence_score") or 0.0) >= 0.70 and float(evaluation.get("compliance_alignment") or 0.0) >= 0.95:
        return "pass"
    if evaluation.get("requires_human_review"):
        return "needs_review"
    return "pass"


def calibrate_critic_verdict(candidate: dict[str, Any], evaluation: dict[str, Any], critic: dict[str, Any]) -> dict[str, Any]:
    expected = deterministic_verdict(candidate, evaluation)
    verdict = normalize_verdict(critic.get("critic_verdict"))

    if expected == "pass" and verdict in {"needs_review", "insufficient_evidence"}:
        critic = dict(critic)
        critic["critic_verdict"] = "pass"
        critic["critic_confidence_adjustment"] = max(0.0, float(critic.get("critic_confidence_adjustment") or 0.0))
        critic["critic_reason"] = "정량 평가상 근거·정합성 기준을 충족하여 LLM Critic의 과도한 재검토 판정을 pass로 보정했다."
        critic["missing_evidence"] = []
        critic["review_questions"] = []
        critic["critic_calibrated"] = True
        return critic

    critic = dict(critic)
    critic["critic_verdict"] = verdict
    critic["critic_calibrated"] = False
    return critic


def fallback_critic(candidate: dict[str, Any], evaluation: dict[str, Any], reason: str) -> dict[str, Any]:
    verdict = deterministic_verdict(candidate, evaluation)
    adjustment = -0.05 if verdict == "insufficient_evidence" else 0.0
    return {
        "critic_verdict": verdict,
        "critic_confidence_adjustment": adjustment,
        "critic_reason": f"LLM Critic 사용 불가로 deterministic 평가 기준을 적용했다. {reason}",
        "missing_evidence": evaluation.get("issues", []) if verdict != "pass" else [],
        "review_questions": [],
        "critic_mode": "deterministic_fallback",
        "critic_calibrated": False,
    }


def run_llm_critic(candidate: dict[str, Any], evaluation: dict[str, Any]) -> dict[str, Any]:
    try:
        prompt = ChatPromptTemplate.from_messages([("system", SYSTEM_PROMPT), ("human", USER_PROMPT)])
        llm = get_chat_model(temperature=0.0)
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
        }
        return calibrate_critic_verdict(candidate, evaluation, critic)
    except Exception as exc:
        return fallback_critic(candidate, evaluation, f"{type(exc).__name__}: {exc}")


def apply_llm_critic_to_evaluation(priority_ranking: dict[str, Any], agent_evaluation: dict[str, Any]) -> dict[str, Any]:
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

        critic = run_llm_critic(candidate, evaluation)
        adjusted_confidence = round(
            max(0.0, min(1.0, float(evaluation.get("confidence_score") or 0.0) + float(critic.get("critic_confidence_adjustment") or 0.0))),
            3,
        )
        evaluation["llm_critic"] = critic
        evaluation["critic_adjusted_confidence_score"] = adjusted_confidence

        copied = dict(candidate)
        copied["agent_evaluation"] = evaluation
        if critic.get("critic_verdict") in {"reject", "insufficient_evidence"} and copied.get("status") == "recommended":
            copied["status"] = "evidence_insufficient"
            copied["reason"] = f"{copied.get('reason', '')} LLM Critic 검토 결과 추가 근거가 필요하다.".strip()
        elif critic.get("critic_verdict") == "needs_review" and copied.get("status") == "recommended":
            copied["status"] = "human_review_required"
            copied["reason"] = f"{copied.get('reason', '')} LLM Critic 검토 결과 Human Review가 필요하다.".strip()
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
        "llm_critic_calibrated_count": sum(
            1 for item in evaluation_map.values()
            if (item.get("llm_critic") or {}).get("critic_calibrated")
        ),
    }
    return {"priority_ranking": updated_ranking, "agent_evaluation": updated_evaluation}
