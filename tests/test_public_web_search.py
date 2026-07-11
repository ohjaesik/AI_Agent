"""public web search provider 결과 정규화와 fallback을 검증한다.
"""

from app.company_bootstrap.public_web_search import build_search_query, discover_public_web_sources, is_allowed_public_result


class DisabledSettings:
    external_web_discovery_enabled = False
    external_web_search_provider = "brave"
    brave_search_api_key = None
    serpapi_api_key = None
    external_web_max_results = 3


def test_public_web_discovery_disabled(monkeypatch):
    monkeypatch.setattr("app.company_bootstrap.public_web_search.get_settings", lambda: DisabledSettings())
    result = discover_public_web_sources("Samsung Electronics", query_terms=["sustainability"])

    assert result["enabled"] is False
    assert result["results"] == []


def test_public_web_blocks_social_domains():
    assert is_allowed_public_result("https://instagram.com/example") is False
    assert is_allowed_public_result("https://example.com/report") is True


def test_build_search_query_includes_company_and_terms():
    query = build_search_query("Samsung Electronics", ["ESG", "governance"])
    assert "Samsung Electronics" in query
    assert "ESG" in query
    assert "governance" in query
