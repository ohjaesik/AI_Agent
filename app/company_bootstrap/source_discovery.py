# app/company_bootstrap/source_discovery.py

"""공식 URL 주변의 추가 공식자료 URL을 탐색한다.

seed URL의 같은 도메인 링크를 따라가며 회사 소개, 사업 영역, ESG/IR 같은 분석 근거
후보를 찾는다.
"""

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
    """공식 도메인 탐색으로 발견한 후보 URL과 점수/근거를 담는 값 객체다."""
    url: str
    reason: str
    score: int

    def to_dict(self) -> dict[str, object]:
        """dataclass/value object를 JSON 직렬화 가능한 dict로 변환한다."""
        return {"url": self.url, "reason": self.reason, "score": self.score}


class LinkParser(HTMLParser):
    """HTML anchor/link tag에서 후보 URL을 수집하는 경량 parser다."""
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[no-untyped-def]
        """HTML anchor tag의 href만 모아 같은 도메인 후보 URL 탐색에 사용한다."""
        if tag.lower() != "a":
            return
        attrs_dict = dict(attrs)
        href = attrs_dict.get("href")
        if href:
            self.links.append(str(href))


def normalize_url(url: str) -> str:
    """normalize_url 함수. 비교/저장/출력을 안정화하기 위해 입력값 형식을 정규화한다."""
    parsed = urllib.parse.urlparse(url)
    parsed = parsed._replace(fragment="")
    return urllib.parse.urlunparse(parsed).rstrip("/")


def same_domain(url: str, base_url: str) -> bool:
    """후보 URL이 seed 공식 URL과 같은 scheme/domain에 있는지 확인한다."""
    parsed = urllib.parse.urlparse(url)
    base = urllib.parse.urlparse(base_url)
    return parsed.scheme in {"http", "https"} and parsed.netloc == base.netloc


def is_candidate_url(url: str) -> bool:
    """이미지/정적 파일을 제외하고 분석 근거로 쓸 만한 keyword URL인지 판단한다."""
    lowered = url.lower()
    if any(lowered.endswith(ext) for ext in BLOCKED_EXTENSIONS):
        return False
    return any(keyword in lowered for keyword in DISCOVERY_KEYWORDS)


def score_url(url: str) -> int:
    """URL 안에 포함된 discovery keyword 수로 공식자료 후보 우선순위를 계산한다."""
    lowered = url.lower()
    return sum(1 for keyword in DISCOVERY_KEYWORDS if keyword in lowered)


def discover_links_from_page(base_url: str, max_candidates: int = 5) -> list[DiscoveredSource]:
    """seed page의 anchor link에서 같은 도메인의 공식자료 후보 URL을 찾는다."""
    html, _content_type = fetch_url(base_url, timeout=12, retries=1)
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
    """seed domain의 sitemap.xml에서 공식자료 후보 URL을 찾는다."""
    parsed = urllib.parse.urlparse(base_url)
    sitemap_url = f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"
    text, _content_type = fetch_url(sitemap_url, timeout=12, retries=1)
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
    """sitemap과 page link 탐색을 조합해 중복 없는 공식자료 후보를 최대 max_total개 반환한다."""
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
