# app/tools/review_applier.py

"""Human Review 결정을 priority ranking에 반영한다.

approve/edit/reject와 promote/exclude/status override를 적용해 최종 후보 상태를 갱신한다.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def reassign_ranks(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """reassign_ranks 함수. Human Review 결정을 priority ranking에 반영한다. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    items.sort(
        key=lambda item: (
            item.get("status") == "recommended",
            float(item.get("final_score") or 0.0),
            float(item.get("saving_rate") or 0.0),
        ),
        reverse=True,
    )

    for rank, item in enumerate(items, start=1):
        item["rank"] = rank

    return items


def build_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    """build_summary 함수. 입력 state나 domain 객체를 조합해 downstream에서 사용할 구조화된 payload를 만든다."""
    recommended = [item for item in items if item.get("status") == "recommended"]
    review_required = [item for item in items if item.get("status") == "human_review_required"]
    excluded = [item for item in items if item.get("status") == "excluded"]

    return {
        "total_candidates": len(items),
        "recommended_count": len(recommended),
        "review_required_count": len(review_required),
        "excluded_count": len(excluded),
        "top_candidate": items[0] if items else None,
    }


def apply_human_review_to_ranking(
    priority_ranking: dict[str, Any],
    human_review: dict[str, Any],
) -> dict[str, Any]:
    """
    Apply reviewer edits to ranking output.

    Supported edited_payload examples:
    {
      "promote_process_ids": [31],
      "exclude_process_ids": [34],
      "status_overrides": {"32": "human_review_required"},
      "score_overrides": {"31": 4.2},
      "reason_overrides": {"31": "현업 요청으로 우선 PoC"}
    }
    """
    result = deepcopy(priority_ranking or {})
    items = result.get("items", [])
    decision = human_review.get("decision", "approve")
    edited_payload = human_review.get("edited_payload") or {}

    if decision == "reject":
        for item in items:
            item["status"] = "excluded"
            item["reason"] = "Human Review에서 PoC 후보에서 제외되었다."
        result["items"] = reassign_ranks(items)
        result["summary"] = build_summary(result["items"])
        result["review_applied"] = True
        return result

    promote_ids = {int(value) for value in edited_payload.get("promote_process_ids", [])}
    exclude_ids = {int(value) for value in edited_payload.get("exclude_process_ids", [])}
    status_overrides = {int(key): value for key, value in edited_payload.get("status_overrides", {}).items()}
    score_overrides = {int(key): float(value) for key, value in edited_payload.get("score_overrides", {}).items()}
    reason_overrides = {int(key): value for key, value in edited_payload.get("reason_overrides", {}).items()}

    for item in items:
        process_id = int(item.get("process_id") or 0)

        if process_id in exclude_ids:
            item["status"] = "excluded"
            item["reason"] = reason_overrides.get(process_id, "Human Review에서 제외 대상으로 지정되었다.")

        if process_id in status_overrides:
            item["status"] = status_overrides[process_id]

        if process_id in score_overrides:
            item["final_score"] = score_overrides[process_id]

        if process_id in promote_ids:
            item["status"] = "recommended"
            item["final_score"] = max(float(item.get("final_score") or 0.0), 5.0)
            item["reason"] = reason_overrides.get(process_id, "Human Review에서 우선 PoC 후보로 승격되었다.")

        if process_id in reason_overrides and process_id not in promote_ids and process_id not in exclude_ids:
            item["reason"] = reason_overrides[process_id]

    result["items"] = reassign_ranks(items)
    result["summary"] = build_summary(result["items"])
    result["review_applied"] = True
    result["review_decision"] = decision

    return result
