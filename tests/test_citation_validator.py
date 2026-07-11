"""보고서 citation validator가 허용/미허용 label을 구분하는지 검증한다.
"""

from app.tools.citation_validator import normalize_citation_label, normalize_citation_labels, validate_report_citations


def test_normalize_combined_official_labels():
    assert normalize_citation_label("[공식URL-1, 공식URL-2]") == ["[공식URL-1]", "[공식URL-2]"]


def test_normalize_labels_preserves_single_label():
    assert normalize_citation_label("[DART-기업개황]") == ["[DART-기업개황]"]


def test_validate_report_accepts_split_combined_labels():
    report_data = {
        "sections": [
            {
                "heading": "1. 분석",
                "blocks": [
                    {
                        "type": "paragraph",
                        "text": "공식자료를 기반으로 분석했다. [공식URL-1, 공식URL-2]",
                    }
                ],
            }
        ],
        "top_candidates": [
            {
                "discovery_metadata": {
                    "evidence_labels": ["[공식URL-1]", "[공식URL-2]"]
                }
            }
        ],
    }

    result = validate_report_citations(report_data=report_data, evidence_items=[])

    assert result["valid"] is True
    assert result["invalid_labels"] == []
    assert normalize_citation_labels(["[공식URL-1, 공식URL-2]"]) == ["[공식URL-1]", "[공식URL-2]"]
