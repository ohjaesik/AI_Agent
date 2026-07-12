# app/evaluation/agent_quality_gold_generator.py

"""Agent 품질 평가용 gold data를 생성한다.

대표 업무/리스크/추천 상태 예시를 만들어 회귀 테스트나 오프라인 평가에 사용한다.
"""

from __future__ import annotations

from typing import Any

FULL_RATIONALE = {
    "expected_effect": "ok",
    "repeatability": "ok",
    "document_dependency": "ok",
    "data_accessibility": "ok",
    "tech_feasibility": "ok",
    "risk_score": "ok",
}
PARTIAL_RATIONALE_3 = {"expected_effect": "ok", "repeatability": "ok", "document_dependency": "ok"}
PARTIAL_RATIONALE_2 = {"expected_effect": "ok", "repeatability": "ok"}


def rationale(kind: str) -> dict[str, str]:
    """gold case에 넣을 score_rationale 충실도 패턴을 반환한다."""
    if kind == "full":
        return dict(FULL_RATIONALE)
    if kind == "partial3":
        return dict(PARTIAL_RATIONALE_3)
    if kind == "partial2":
        return dict(PARTIAL_RATIONALE_2)
    return {}


def labels(count: int) -> list[str]:
    """요청한 개수만큼 공식자료 citation label 샘플을 반환한다."""
    return ["[공식URL-1]", "[공식URL-2]", "[DART-기업개황]"][:count]


def compliance(process_id: int, level: str, blocked: bool = False) -> dict[str, Any]:
    """gold case에 붙일 compliance assessment 샘플 payload를 만든다."""
    return {"process_id": process_id, "compliance_level": level, "human_review_required": True, "blocked": blocked}


def make_case(
    idx: int,
    name: str,
    *,
    initial_status: str = "recommended",
    evidence_label_count: int = 2,
    context_count: int = 3,
    evidence_count: int = 2,
    data_accessibility: int = 4,
    risk_score: int = 1,
    rationale_kind: str = "full",
    expected_status: str = "recommended",
    expected_review: bool = False,
    compliance_level: str | None = None,
    blocked: bool = False,
    replan: bool = False,
) -> dict[str, Any]:
    """Agent evaluator 회귀 테스트용 gold case 하나를 생성한다."""
    process_id = 100 + idx
    case: dict[str, Any] = {
        "case_id": f"gold-{idx:03d}",
        "process_id": process_id,
        "candidate_agent_name": name,
        "initial_status": initial_status,
        "evidence_labels": labels(evidence_label_count),
        "context_count": context_count,
        "evidence_count": evidence_count,
        "data_accessibility": data_accessibility,
        "risk_score": risk_score,
        "score_rationale": rationale(rationale_kind),
        "final_score": 4.0 if expected_status == "recommended" else 3.2,
        "saving_rate": 60.0 if expected_status == "recommended" else 35.0,
        "expected_status": expected_status,
        "expected_requires_human_review": expected_review,
    }
    if compliance_level:
        case["compliance"] = compliance(process_id, compliance_level, blocked=blocked)
    if replan:
        case["replan_source_collection"] = {
            "public_web_search": {"results": [{"url": "https://example.com/source-a"}, {"url": "https://example.com/source-b"}, {"url": "https://example.com/source-c"}]},
            "same_domain_discovered": [],
            "indexed_chunks": 47,
        }
    return case


def build_additional_gold_cases() -> list[dict[str, Any]]:
    """build_additional_gold_cases 함수. 입력 state나 domain 객체를 조합해 downstream에서 사용할 구조화된 payload를 만든다."""
    cases: list[dict[str, Any]] = []

    compliance_cases = [
        ("HR Screening Agent", "enhanced_review", 4),
        ("Finance Approval Agent", "enhanced_review", 4),
        ("Safety Incident Agent", "enhanced_review", 4),
        ("Student Evaluation Agent", "enhanced_review", 5),
        ("Legal Advice Agent", "enhanced_review", 5),
        ("Healthcare Triage Agent", "enhanced_review", 5),
        ("Credit Support Agent", "enhanced_review", 4),
        ("Sensitive Data Agent", "sensitive_review", 2),
        ("Privacy Request Agent", "sensitive_review", 3),
        ("Confidential Workflow Agent", "sensitive_review", 2),
        ("Personal Data Merge Agent", "sensitive_review", 4),
        ("Customer Data Insight Agent", "sensitive_review", 3),
        ("EHS Compliance Monitor Agent", "sensitive_review", 3),
        ("Environmental Compliance Monitor Agent", "sensitive_review", 3),
        ("Legal Clause Review Agent", "enhanced_review", 4),
    ]
    for offset, (name, level, risk) in enumerate(compliance_cases, start=51):
        cases.append(make_case(offset, name, risk_score=risk, compliance_level=level, expected_status="human_review_required", expected_review=True))

    evidence_gap_cases = [
        ("Low Evidence Agent", 0, 0, 0, 3, 3, "none"),
        ("Very Low Evidence Agent", 0, 1, 0, 1, 4, "none"),
        ("No Context No Evidence Agent", 0, 0, 0, 1, 1, "partial2"),
        ("Weak ROI Evidence Agent", 1, 0, 0, 2, 3, "partial2"),
        ("No Rationale No Context Agent", 1, 0, 0, 3, 3, "none"),
        ("Unverified Claim Agent", 0, 1, 0, 3, 2, "partial3"),
        ("Dataset Missing Agent", 1, 0, 0, 1, 2, "full"),
        ("Evidence Gap Agent", 0, 0, 1, 2, 3, "partial2"),
        ("Source Missing Agent", 0, 2, 0, 2, 2, "partial3"),
        ("Thin Citation Agent", 1, 0, 1, 1, 4, "partial2"),
        ("Unknown Data Access Agent", 0, 1, 1, 1, 3, "none"),
        ("No Tool Output Agent", 0, 0, 0, 4, 1, "full"),
        ("Broken Evidence Agent", 1, 0, 0, 1, 5, "partial3"),
        ("Low Confidence Agent", 0, 1, 0, 2, 4, "none"),
        ("Unsupported Automation Agent", 0, 0, 1, 3, 5, "partial2"),
        ("Missing Policy Agent", 1, 0, 0, 2, 2, "partial3"),
        ("Evidence Starved Agent", 0, 0, 0, 5, 1, "none"),
    ]
    for offset, (name, label_count, ctx, evidence, data, risk, rat) in enumerate(evidence_gap_cases, start=66):
        cases.append(
            make_case(
                offset,
                name,
                evidence_label_count=label_count,
                context_count=ctx,
                evidence_count=evidence,
                data_accessibility=data,
                risk_score=risk,
                rationale_kind=rat,
                expected_status="evidence_insufficient",
                expected_review=True,
            )
        )

    # Nonzero but weak evidence should be reviewed by a person rather than treated
    # as completely insufficient.
    cases.append(
        make_case(
            83,
            "Weakly Supported ROI Agent",
            evidence_label_count=1,
            context_count=1,
            evidence_count=1,
            data_accessibility=2,
            risk_score=2,
            rationale_kind="partial2",
            expected_status="human_review_required",
            expected_review=True,
        )
    )

    blocked_cases = [
        "Blocked Agent",
        "Autonomous Execution Agent",
        "Manipulative Targeting Agent",
        "Prohibited Scoring Agent",
        "Unsafe Biometric Agent",
        "Unauthorized Action Agent",
        "Subliminal Targeting Agent",
        "Predictive Policing Agent",
    ]
    for offset, name in enumerate(blocked_cases, start=84):
        cases.append(make_case(offset, name, evidence_label_count=1, context_count=2, evidence_count=1, data_accessibility=3, risk_score=5, rationale_kind="partial3", compliance_level="blocked", blocked=True, expected_status="excluded", expected_review=True))

    for offset, name in enumerate(["Post Replan Product Advisor", "Post Replan ESG Assistant", "Post Replan Service Agent", "Post Replan Knowledge Agent"], start=92):
        cases.append(make_case(offset, name, evidence_label_count=2, context_count=3, evidence_count=1, data_accessibility=4, risk_score=1, replan=True, expected_status="recommended", expected_review=False))

    for offset, name in enumerate(["Simple Search Agent", "Catalog Summary Agent", "Partner FAQ Agent", "Training Quiz Agent", "Operations Insight Agent"], start=96):
        cases.append(make_case(offset, name, evidence_label_count=2, context_count=3, evidence_count=2, data_accessibility=4, risk_score=1, expected_status="recommended", expected_review=False))

    return cases
