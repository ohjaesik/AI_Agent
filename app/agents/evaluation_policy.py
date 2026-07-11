# app/agents/evaluation_policy.py
"""Evaluation/Critic Agent가 공유하는 추천 상태 정책을 모은다.

Evaluator, LLM Critic, Expert Executor가 각각 같은 판단식을 따로 들고 있으면
`추가 근거 필요`, `자동 replan`, `Human Review`, `심각한 근거 부족`의 경계가
조금씩 어긋난다. 이 모듈은 그 경계를 한 군데에 고정해 workflow_state와 보고서가
같은 의미의 상태값을 보도록 만든다.
"""

from __future__ import annotations

from typing import Any

REVIEW_LEVELS = {"enhanced_review", "sensitive_review"}
VALID_CRITIC_VERDICTS = {"pass", "needs_replan", "needs_review", "insufficient_evidence", "reject"}

VERY_WEAK_EVIDENCE_THRESHOLD = 0.15
EVIDENCE_INSUFFICIENT_THRESHOLD = 0.15
LOW_CONFIDENCE_THRESHOLD = 0.45

AUTONOMY_ROUTE_SEVERE_EVIDENCE_GAP = "severe_evidence_gap"
AUTONOMY_ROUTE_AUTO_REPLAN = "auto_replan"
AUTONOMY_ROUTE_HUMAN_REVIEW = "human_review"
AUTONOMY_ROUTE_AUTONOMOUS_PASS = "autonomous_pass"


def as_float(value: Any, default: float = 0.0) -> float:
    """정책 계산에 들어오는 숫자형 값을 안전하게 float로 변환한다."""

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def compliance_requires_human_review(compliance: dict[str, Any]) -> bool:
    """규제/민감도 때문에 자동 확정하면 안 되는 후보인지 판단한다."""

    return bool(compliance.get("human_review_required")) or compliance.get("compliance_level") in REVIEW_LEVELS


def is_very_weak_evidence(evidence_coverage: float, data_confidence: float) -> bool:
    """근거가 자동 replan 전에도 추천 상태로 두기 어려울 정도로 약한지 판정한다."""

    return evidence_coverage < VERY_WEAK_EVIDENCE_THRESHOLD or (
        evidence_coverage < 0.20 and data_confidence < 0.30
    )


def build_evaluation_route(
    *,
    candidate_status: str | None,
    compliance: dict[str, Any],
    risk_uncertainty: float,
    confidence_score: float,
    human_review_threshold: float,
    issues: list[str],
    requires_additional_evidence: bool,
    zero_evidence_coverage: bool,
    very_weak_evidence_coverage: bool,
) -> dict[str, Any]:
    """Evaluator가 후보별 자율 처리 경로와 Human Review 필요 여부를 결정한다."""

    governance_review_required = (
        compliance_requires_human_review(compliance)
        or candidate_status == "human_review_required"
        or risk_uncertainty >= 0.45
    )
    requires_human_review = (
        governance_review_required
        or (not requires_additional_evidence and (confidence_score < human_review_threshold or bool(issues)))
    )

    if zero_evidence_coverage or very_weak_evidence_coverage:
        autonomy_route = AUTONOMY_ROUTE_SEVERE_EVIDENCE_GAP
    elif requires_additional_evidence:
        autonomy_route = AUTONOMY_ROUTE_AUTO_REPLAN
    elif requires_human_review:
        autonomy_route = AUTONOMY_ROUTE_HUMAN_REVIEW
    else:
        autonomy_route = AUTONOMY_ROUTE_AUTONOMOUS_PASS

    return {
        "requires_human_review": requires_human_review,
        "autonomy_route": autonomy_route,
    }


def normalize_critic_verdict(value: Any) -> str:
    """LLM Critic이 반환한 verdict 문자열을 허용된 값으로 정규화한다."""

    verdict = str(value or "needs_review").strip().lower()
    return verdict if verdict in VALID_CRITIC_VERDICTS else "needs_review"


def evaluation_has_severe_evidence_gap(evaluation: dict[str, Any]) -> bool:
    """평가 결과가 replan보다 먼저 추천 보류가 필요한 심각한 근거 부족인지 판단한다."""

    evidence_coverage_value = evaluation.get("evidence_coverage")
    evidence_coverage = as_float(evidence_coverage_value, 0.0)
    has_evidence_coverage = evidence_coverage_value is not None
    return (
        bool(evaluation.get("zero_evidence_coverage"))
        or bool(evaluation.get("very_weak_evidence_coverage"))
        or (
            bool(evaluation.get("requires_additional_evidence"))
            and has_evidence_coverage
            and evidence_coverage <= EVIDENCE_INSUFFICIENT_THRESHOLD
        )
    )


def deterministic_critic_verdict(candidate: dict[str, Any], evaluation: dict[str, Any]) -> str:
    """LLM Critic 실패 시에도 같은 정책으로 fallback verdict를 만든다."""

    compliance = candidate.get("compliance") or {}
    if compliance.get("blocked"):
        return "reject"
    if evaluation_has_severe_evidence_gap(evaluation):
        return "insufficient_evidence"
    if evaluation.get("requires_additional_evidence"):
        return "needs_replan"
    if compliance.get("compliance_level") in REVIEW_LEVELS:
        return "needs_review"
    if evaluation.get("issues"):
        return "needs_review"
    if as_float(evaluation.get("confidence_score"), 0.0) >= 0.70 and as_float(evaluation.get("compliance_alignment"), 0.0) >= 0.95:
        return "pass"
    if evaluation.get("requires_human_review"):
        return "needs_review"
    return "pass"


def split_evidence_decision_ids(agent_evaluation: dict[str, Any]) -> tuple[set[int], set[int], set[int]]:
    """평가 결과를 심각한 근거 부족, 사람 검토, 자동 replan 대상으로 분리한다."""

    insufficient_ids: set[int] = set()
    review_ids: set[int] = set()
    replan_ids: set[int] = set()

    for item in agent_evaluation.get("items", []) or []:
        process_id = int(item.get("process_id") or 0)
        if not process_id:
            continue

        confidence_score = as_float(item.get("confidence_score"), 0.0)
        predicted_status = str(item.get("predicted_status") or "")
        requires_additional_evidence = bool(item.get("requires_additional_evidence"))
        requires_human_review = bool(item.get("requires_human_review"))
        critic = item.get("llm_critic") or {}
        critic_verdict_value = critic.get("critic_verdict")
        critic_verdict = normalize_critic_verdict(critic_verdict_value) if critic_verdict_value else ""

        severe_low_confidence = confidence_score < LOW_CONFIDENCE_THRESHOLD
        explicit_insufficient = predicted_status == "evidence_insufficient"

        if critic_verdict == "reject" or evaluation_has_severe_evidence_gap(item) or (explicit_insufficient and severe_low_confidence):
            insufficient_ids.add(process_id)
        elif requires_human_review or critic_verdict in {"needs_review", "revise"}:
            review_ids.add(process_id)
        elif requires_additional_evidence or explicit_insufficient or critic_verdict == "needs_replan":
            replan_ids.add(process_id)

    review_ids -= insufficient_ids
    replan_ids -= insufficient_ids | review_ids
    return insufficient_ids, review_ids, replan_ids
