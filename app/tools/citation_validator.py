# app/tools/citation_validator.py

"""보고서 citation label 검증 tool.

report paragraph 안의 citation이 실제 used_sources/evidence label 안에 존재하는지 확인한다.
"""

from __future__ import annotations

import re
from typing import Any

CITATION_PATTERN = re.compile(r"\[[^\[\]]+\]")
OFFICIAL_DISCOVERY_PATTERN = re.compile(r"^\[(공식URL-\d+|DART-기업개황)\]$")


def collect_allowed_citation_labels(evidence_items: list[dict[str, Any]]) -> set[str]:
    """evidence_items에서 보고서가 인용해도 되는 citation label 집합을 만든다."""
    return {
        str(item["citation_label"])
        for item in evidence_items
        if item.get("citation_label")
    }


def normalize_citation_label(label: str) -> list[str]:
    """Split labels like '[공식URL-1, 공식URL-2]' into valid individual labels."""
    raw = str(label or "").strip()
    if not raw.startswith("[") or not raw.endswith("]"):
        return []

    inner = raw[1:-1].strip()
    if not inner:
        return []

    parts = [part.strip() for part in re.split(r"[,，]", inner) if part.strip()]
    if len(parts) <= 1:
        return [raw]

    return [f"[{part}]" for part in parts]


def normalize_citation_labels(labels: list[str]) -> list[str]:
    """복합 citation label을 개별 label로 풀고 중복 없이 순서를 유지한다."""
    result: list[str] = []
    for label in labels:
        for normalized in normalize_citation_label(label):
            if normalized not in result:
                result.append(normalized)
    return result


def collect_official_discovery_labels(report_data: dict[str, Any]) -> set[str]:
    """후보 discovery metadata와 본문에서 공식자료 citation label을 추가 수집한다."""
    labels: set[str] = set()

    for candidate in report_data.get("top_candidates", []):
        metadata = candidate.get("discovery_metadata") or {}
        for label in metadata.get("evidence_labels", []):
            labels.add(str(label))

        for text in [
            candidate.get("problem"),
            candidate.get("reason"),
            candidate.get("suitability_rationale"),
        ]:
            for label in normalize_citation_labels(find_citation_labels(str(text or ""))):
                if OFFICIAL_DISCOVERY_PATTERN.match(label):
                    labels.add(label)

        for text in (candidate.get("score_rationale") or {}).values():
            for label in normalize_citation_labels(find_citation_labels(str(text or ""))):
                if OFFICIAL_DISCOVERY_PATTERN.match(label):
                    labels.add(label)

    return labels


def collect_texts_from_report_data(report_data: dict[str, Any]) -> list[str]:
    """citation 검사를 위해 report section과 top candidate 설명 문장을 모두 모은다."""
    texts: list[str] = []

    for section in report_data.get("sections", []):
        for block in section.get("blocks", []):
            if block.get("type") == "paragraph":
                texts.append(str(block.get("text", "")))

    for candidate in report_data.get("top_candidates", []):
        for key in ["problem", "reason", "suitability_rationale"]:
            texts.append(str(candidate.get(key, "")))
        for value in (candidate.get("score_rationale") or {}).values():
            texts.append(str(value))

    return texts


def find_citation_labels(text: str) -> list[str]:
    """문장 안의 대괄호 citation label 패턴을 모두 찾는다."""
    return CITATION_PATTERN.findall(text or "")


def validate_report_citations(
    report_data: dict[str, Any],
    evidence_items: list[dict[str, Any]],
) -> dict[str, Any]:
    """보고서 문단의 citation label이 허용된 source/evidence 안에 있는지 검증한다."""
    allowed = collect_allowed_citation_labels(evidence_items)
    allowed.update(collect_official_discovery_labels(report_data))

    found: list[str] = []
    invalid: list[str] = []
    paragraphs_without_citation = 0

    for text in collect_texts_from_report_data(report_data):
        raw_labels = find_citation_labels(text)
        labels = normalize_citation_labels(raw_labels)

        if not labels:
            paragraphs_without_citation += 1
            continue

        for label in labels:
            if label not in found:
                found.append(label)
            if label not in allowed and label not in invalid:
                invalid.append(label)

    return {
        "valid": len(invalid) == 0,
        "allowed_count": len(allowed),
        "found_count": len(found),
        "invalid_labels": invalid,
        "paragraphs_without_citation": paragraphs_without_citation,
    }
