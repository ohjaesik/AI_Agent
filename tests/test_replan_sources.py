"""replan source 수집 helper의 seed URL/query term 생성을 검증한다."""

from app.graph.replan_sources import official_seed_urls, replan_query_terms


def test_official_seed_urls_dedupes_used_sources_and_documents() -> None:
    seed_urls, existing_urls = official_seed_urls(
        {
            "used_sources": [
                {"url": "https://example.com/company"},
                {"source_url": "https://example.com/company"},
            ],
            "documents": [
                {"source_url": "https://example.com/report"},
                {"url": "not-a-url"},
            ],
        }
    )

    assert seed_urls == ["https://example.com/company", "https://example.com/report"]
    assert existing_urls == {"https://example.com/company", "https://example.com/report"}


def test_replan_query_terms_dedupes_candidate_and_company_terms() -> None:
    terms = replan_query_terms(
        {"company_profile": {"name": "DemoCo"}},
        [
            {
                "process_name": "SOP 검색",
                "candidate_agent_name": "SOP Search Agent",
                "requery_terms": ["SOP 검색", "규정", "SOP"],
            }
        ],
    )

    assert terms == ["SOP 검색", "SOP Search Agent", "규정", "SOP", "DemoCo"]
