from app.chains.report_writer import enforce_citation_coverage


def test_enforce_citation_coverage_appends_default_label():
    report_data = {
        "sections": [
            {
                "heading": "1. 테스트",
                "blocks": [
                    {
                        "type": "paragraph",
                        "text": "이 문단은 근거가 필요한 분석 문장으로 충분히 길지만 아직 citation label이 없다.",
                    },
                    {
                        "type": "paragraph",
                        "text": "이미 citation이 있는 문단이다. [공식URL-1]",
                    },
                ],
            }
        ],
        "generation": {"mode": "vllm_report_writer", "warnings": []},
    }
    evidence_items = [{"citation_label": "[공식URL-1]", "confidence": 0.9}]

    updated = enforce_citation_coverage(report_data, ["[공식URL-1]"], evidence_items)

    paragraphs = [block["text"] for block in updated["sections"][0]["blocks"]]
    assert paragraphs[0].endswith("[공식URL-1]")
    assert paragraphs[1].count("[공식URL-1]") == 1
    assert updated["generation"]["warnings"]
