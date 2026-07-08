# app/company_bootstrap/url_loader.py

from __future__ import annotations

import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlparse


@dataclass(frozen=True)
class OfficialUrlDocument:
    url: str
    title: str
    content: str


class ReadableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.current_tag: str | None = None
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[no-untyped-def]
        self.current_tag = tag.lower()

        if self.current_tag in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1

        if self.current_tag in {"p", "br", "li", "div", "section", "article", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()

        if tag in {"script", "style", "noscript", "svg"} and self.skip_depth > 0:
            self.skip_depth -= 1

        if tag in {"p", "li", "div", "section", "article", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

        self.current_tag = None

    def handle_data(self, data: str) -> None:
        if self.skip_depth > 0:
            return

        text = data.strip()
        if not text:
            return

        if self.current_tag == "title":
            self.title_parts.append(text)
        else:
            self.parts.append(text)

    def get_title(self, fallback: str) -> str:
        title = " ".join(self.title_parts).strip()
        return normalize_whitespace(title) or fallback

    def get_text(self) -> str:
        return normalize_text(" ".join(self.parts))


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_text(text: str) -> str:
    lines = [normalize_whitespace(line) for line in re.split(r"[\r\n]+", text or "")]
    lines = [line for line in lines if line]
    joined = "\n".join(lines)
    joined = re.sub(r"\n{3,}", "\n\n", joined)
    return joined.strip()


def fetch_url_once(url: str, timeout: int = 15) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "AX-Delivery-Planner/0.1 (+https://github.com/ohjaesik/AI_Agent)",
        },
    )

    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - user-provided official URL only
        raw = response.read()
        charset = response.headers.get_content_charset() or "utf-8"

    try:
        return raw.decode(charset)
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="ignore")


def fetch_url(url: str, timeout: int = 15, retries: int = 2, backoff_seconds: float = 1.0) -> str:
    last_error: Exception | None = None

    for attempt in range(retries + 1):
        try:
            return fetch_url_once(url=url, timeout=timeout)
        except (TimeoutError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            last_error = exc
            if attempt >= retries:
                break
            time.sleep(backoff_seconds * (2**attempt))

    assert last_error is not None
    raise last_error


def fallback_title_from_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc or "official-url"
    path = parsed.path.strip("/") or "home"
    return f"{host} {path}"


def load_official_url(url: str, max_chars: int = 20000) -> OfficialUrlDocument:
    html = fetch_url(url)
    parser = ReadableHTMLParser()
    parser.feed(html)

    fallback_title = fallback_title_from_url(url)
    title = parser.get_title(fallback=fallback_title)
    content = parser.get_text()

    if not content:
        content = normalize_text(re.sub(r"<[^>]+>", " ", html))

    if len(content) > max_chars:
        content = content[:max_chars] + "..."

    return OfficialUrlDocument(
        url=url,
        title=title,
        content=content,
    )
