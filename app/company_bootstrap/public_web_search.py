# app/company_bootstrap/public_web_search.py

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings

PUBLIC_SOURCE_HINTS = {
    "site:sec.gov",
    "site:dart.fss.or.kr",
    "site:opencorporates.com",
    "site:wikipedia.org",
}

BLOCKED_DOMAINS = {
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "youtube.com",
    "tiktok.com",
    "reddit.com",
    "pinterest.com",
}


@dataclass(frozen=True)
class PublicWebResult:
    title: str
    url: str
    snippet: str
    provider: str
    score: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "provider": self.provider,
            "score": self.score,
        }


def normalize_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    parsed = parsed._replace(fragment="")
    return urllib.parse.urlunparse(parsed).rstrip("/")


def domain_of(url: str) -> str:
    return urllib.parse.urlparse(url).netloc.lower().removeprefix("www.")


def is_allowed_public_result(url: str, existing_domains: set[str] | None = None) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    domain = domain_of(url)
    if not domain:
        return False
    if any(domain == blocked or domain.endswith(f".{blocked}") for blocked in BLOCKED_DOMAINS):
        return False
    if existing_domains and domain in existing_domains:
        return True
    return True


def build_search_query(company_name: str, query_terms: list[str] | None = None) -> str:
    terms = [company_name, "AI", "automation", "governance", "sustainability", "report"]
    terms.extend(term for term in (query_terms or []) if term)
    deduped: list[str] = []
    seen = set()
    for term in terms:
        normalized = str(term).strip()
        if not normalized or normalized.lower() in seen:
            continue
        seen.add(normalized.lower())
        deduped.append(normalized)
    return " ".join(deduped[:10])


def score_result(result: PublicWebResult, company_name: str, existing_domains: set[str]) -> int:
    score = result.score
    text = f"{result.title} {result.url} {result.snippet}".lower()
    if company_name.lower() in text:
        score += 3
    if any(keyword in text for keyword in ["sustainability", "governance", "compliance", "annual report", "business report", "privacy", "security"]):
        score += 2
    if domain_of(result.url) in existing_domains:
        score += 2
    return score


def brave_search(query: str, max_results: int) -> list[PublicWebResult]:
    settings = get_settings()
    if not settings.brave_search_api_key:
        return []
    params = urllib.parse.urlencode({"q": query, "count": max_results, "search_lang": "en"})
    request = urllib.request.Request(
        f"https://api.search.brave.com/res/v1/web/search?{params}",
        headers={"Accept": "application/json", "X-Subscription-Token": settings.brave_search_api_key},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 - explicit opt-in external search
        payload = json.loads(response.read().decode("utf-8"))

    results = []
    for item in (payload.get("web") or {}).get("results", [])[:max_results]:
        url = normalize_url(str(item.get("url") or ""))
        if not url:
            continue
        results.append(
            PublicWebResult(
                title=str(item.get("title") or ""),
                url=url,
                snippet=str(item.get("description") or ""),
                provider="brave",
                score=1,
            )
        )
    return results


def serpapi_search(query: str, max_results: int) -> list[PublicWebResult]:
    settings = get_settings()
    if not settings.serpapi_api_key:
        return []
    params = urllib.parse.urlencode({"engine": "google", "q": query, "api_key": settings.serpapi_api_key, "num": max_results})
    request = urllib.request.Request(f"https://serpapi.com/search.json?{params}", method="GET")
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 - explicit opt-in external search
        payload = json.loads(response.read().decode("utf-8"))

    results = []
    for item in payload.get("organic_results", [])[:max_results]:
        url = normalize_url(str(item.get("link") or ""))
        if not url:
            continue
        results.append(
            PublicWebResult(
                title=str(item.get("title") or ""),
                url=url,
                snippet=str(item.get("snippet") or ""),
                provider="serpapi",
                score=1,
            )
        )
    return results


def discover_public_web_sources(
    company_name: str,
    query_terms: list[str] | None = None,
    existing_urls: set[str] | None = None,
    max_results: int | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.external_web_discovery_enabled:
        return {"enabled": False, "provider": settings.external_web_search_provider, "query": None, "results": [], "warnings": ["External web discovery is disabled."]}

    limit = max_results or settings.external_web_max_results
    existing = {normalize_url(url) for url in (existing_urls or set()) if url}
    existing_domains = {domain_of(url) for url in existing if url}
    query = build_search_query(company_name=company_name, query_terms=query_terms)

    provider = settings.external_web_search_provider.lower()
    warnings: list[str] = []
    try:
        if provider == "brave":
            raw_results = brave_search(query, max_results=limit * 2)
        elif provider == "serpapi":
            raw_results = serpapi_search(query, max_results=limit * 2)
        else:
            return {"enabled": True, "provider": provider, "query": query, "results": [], "warnings": [f"Unsupported provider: {provider}"]}
    except Exception as exc:
        return {"enabled": True, "provider": provider, "query": query, "results": [], "warnings": [f"Search failed: {type(exc).__name__}: {exc}"]}

    scored: list[PublicWebResult] = []
    seen = set(existing)
    for result in raw_results:
        normalized = normalize_url(result.url)
        if normalized in seen:
            continue
        if not is_allowed_public_result(normalized, existing_domains=existing_domains):
            continue
        seen.add(normalized)
        scored.append(
            PublicWebResult(
                title=result.title,
                url=normalized,
                snippet=result.snippet,
                provider=result.provider,
                score=score_result(result, company_name=company_name, existing_domains=existing_domains),
            )
        )

    scored.sort(key=lambda item: item.score, reverse=True)
    if not scored:
        warnings.append("No usable public web search results after filtering.")

    return {
        "enabled": True,
        "provider": provider,
        "query": query,
        "results": [item.to_dict() for item in scored[:limit]],
        "warnings": warnings,
    }
