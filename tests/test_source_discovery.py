"""공식 URL source discovery가 같은 도메인 후보를 찾는지 검증한다.
"""

from app.company_bootstrap.source_discovery import is_candidate_url, normalize_url, same_domain, score_url


def test_normalize_url_removes_fragment_and_trailing_slash():
    assert normalize_url("https://example.com/about/#top") == "https://example.com/about"


def test_same_domain_only_accepts_same_host():
    assert same_domain("https://example.com/sustainability", "https://example.com/about") is True
    assert same_domain("https://other.com/sustainability", "https://example.com/about") is False


def test_candidate_url_prefers_governance_keywords():
    assert is_candidate_url("https://example.com/sustainability/governance") is True
    assert is_candidate_url("https://example.com/static/logo.png") is False
    assert score_url("https://example.com/sustainability/governance/report") >= 2
