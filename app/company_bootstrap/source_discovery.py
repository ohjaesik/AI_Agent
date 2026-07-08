# app/company_bootstrap/source_discovery.py

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from html.parser import HTMLParser

from app.company_bootstrap.url_loader import fetch_url

DISCOVERY_KEYWORDS = [
    "sustainability",
    "esg",
    "governance",
    "compliance",
    "ethics",
    "privacy",
    "security",
    "business",
    "about",
    "company",
    "investor",
    "ir",
    "report",
    "policy",
    "overview",
]

BLOCKED_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".svg",
    ".webp",
    ".mp4",
    ".avi",
    ".mov",
    ".zip",
    ".css",
    ".js",
)


@dataclass(frozen=True)
class DiscoveredSource:
    url: str
    reason: str
    score: int

    def to_dict(self) -> dict[str, object]:
        return {"url": self.url, "reason": self.reason, "score": self.score}


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[no-untyped-def]
        if tag.lower() != "a":
            return
        attrs_dict = dict(attrs)
        href = attrs_dict.get("href")
        if href:
            self.links.append(str(href))


def normalize_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    parsed = parsed._replace(fragment="")
    return urllib.parse.urlunparse(parsed).rstrip("/")


def same_domain(url: str, base_url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    base = urllib.parse.urlparse(base_url)
    return parsed.scheme in {"http", "https"} and parsed.netloc == base.netloc


def is_candidate_url(url: str) -> bool:
    lowered = url.lower()
    if any(lowered.endswith(ext) for ext in BLOCKED_EXTENSIONS):
        return False
    return any(keyword in lowered for keyword in DISCOVERY_KEYWORDS)


def score_url(url: str) -> int:
    lowered = url.lower()
    return sum(1 for keyword in DISCOVERY_KEYWORDS if keyword in lowered)


def discover_links_from_page(base_url: str, max_candidates: int = 5) -> list[DiscoveredSource]:
    html = fetch_url(base_url, timeout=12, retries=1)
    parser = LinkParser()
    parser.feed(html)

    seen: set[str] = set()
    candidates: list[DiscoveredSource] = []
    for href in parser.links:
        absolute = normalize_url(urllib.parse.urljoin(base_url, href))
        if absolute in seen:
            continue
        seen.add(absolute)
        if not same_domain(absolute, base_url) or not is_candidate_url(absolute):
            continue
        candidates.append(
            DiscoveredSource(
                url=absolute,
                reason="same-domain keyword link discovered from official page",
                score=score_url(absolute),
            )
        )

    candidates.sort(key=lambda item: (item.score, len(item.url)), reverse=True)
    return candidates[:max_candidates]


def discover_from_sitemap(base_url: str, max_candidates: int = 5) -> list[DiscoveredSource]:
    parsed = urllib.parse.urlparse(base_url)
    sitemap_url = f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"
    text = fetch_url(sitemap_url, timeout=12, retries=1)
    urls = re.findall(r"<loc>(.*?)</loc>", text, flags=re.IGNORECASE | re.DOTALL)

    candidates = []
    seen: set[str] = set()
    for raw in urls:
        url = normalize_url(raw.strip())
        if url in seen:
            continue
        seen.add(url)
        if same_domain(url, base_url) and is_candidate_url(url):
            candidates.append(
                DiscoveredSource(
                    url=url,
                    reason="same-domain keyword URL discovered from sitemap.xml",
                    score=score_url(url) + 1,
                )
            )
    candidates.sort(key=lambda item: (item.score, len(item.url)), reverse=True)
    return candidates[:max_candidates]


def discover_official_sources(seed_urls: list[str], existing_urls: set[str] | None = None, max_total: int = 5) -> list[DiscoveredSource]:
    existing = {normalize_url(url) for url in (existing_urls or set()) if url}
    output: list[DiscoveredSource] = []
    seen = set(existing)

    for seed in seed_urls:
        for loader in (discover_from_sitemap, discover_links_from_page):
            try:
                discovered = loader(seed, max_candidates=max_total)
            except Exception:
                continue
            for item in discovered:
                normalized = normalize_url(item.url)
                if normalized in seen:
                    continue
                seen.add(normalized)
                output.append(item)
                if len(output) >= max_total:
                    return output

    return output
