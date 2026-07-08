# app/tools/citation_validator.py

from __future__ import annotations

import re
from typing import Any

CITATION_PATTERN = re.compile(r"\[[^\[\]]+\]")
OFFICIAL_DISCOVERY_PATTERN = re.compile(r"^\[(공식URL-\d+|DART-기업개황)\]$")


def collect_allowed_citation_labels(evidence_items: list[dict[str, Any]]) -> set[str]:
    return {
        str(item["citation_label"])
        for item in evidence_items
        if item.get("citation_label")
    }


def collect_official_discovery_labels(report_data: dict[str, Any]) -> set[str]:
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
            for label in find_citation_labels(str(text or "")):
                if OFFICIAL_DISCOVERY_PATTERN.match(label):
                    labels.add(label)

        for text in (candidate.get("score_rationale") or {}).values():
            for label in find_citation_labels(str(text or "")):
                if OFFICIAL_DISCOVERY_PATTERN.match(label):
                    labels.add(label)

    return labels


def collect_texts_from_report_data(report_data: dict[str, Any]) -> list[str]:
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
    return CITATION_PATTERN.findall(text or "")


def validate_report_citations(
    report_data: dict[str, Any],
    evidence_items: list[dict[str, Any]],
) -> dict[str, Any]:
    allowed = collect_allowed_citation_labels(evidence_items)
    allowed.update(collect_official_discovery_labels(report_data))

    found: list[str] = []
    invalid: list[str] = []
    paragraphs_without_citation = 0

    for text in collect_texts_from_report_data(report_data):
        labels = find_citation_labels(text)

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
