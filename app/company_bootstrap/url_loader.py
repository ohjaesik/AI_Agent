# app/company_bootstrap/url_loader.py

"""공식 URL 본문을 로드하고 텍스트로 정리한다.

HTML 페이지를 가져와 title, 본문 텍스트, URL metadata를 추출하고 source document로
저장 가능한 구조로 반환한다.
"""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlparse


PDF_PLACEHOLDER = (
    "이 URL은 PDF 또는 바이너리 문서로 감지되어 HTML 본문 자동 추출을 수행하지 않았다. "
    "정확한 본문 근거가 필요한 경우 PDF 전용 수집기 또는 파일 업로드 기반 ingestion을 사용해야 한다."
)


@dataclass(frozen=True)
class OfficialUrlDocument:
    """공식 URL에서 로드한 title/body/source metadata를 담는 값 객체다."""
    url: str
    title: str
    content: str


class ReadableHTMLParser(HTMLParser):
    """HTML에서 script/style을 제외하고 사람이 읽을 수 있는 본문 텍스트를 추출하는 parser다."""
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.current_tag: str | None = None
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[no-untyped-def]
        """본문 구분용 줄바꿈을 넣고 script/style 계층은 건너뛰도록 표시한다."""
        self.current_tag = tag.lower()

        if self.current_tag in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1

        if self.current_tag in {"p", "br", "li", "div", "section", "article", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        """읽을 수 있는 block tag가 끝날 때 줄바꿈을 추가하고 skip depth를 복구한다."""
        tag = tag.lower()

        if tag in {"script", "style", "noscript", "svg"} and self.skip_depth > 0:
            self.skip_depth -= 1

        if tag in {"p", "li", "div", "section", "article", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

        self.current_tag = None

    def handle_data(self, data: str) -> None:
        """HTML text node를 title 또는 본문 조각으로 분리해 저장한다."""
        if self.skip_depth > 0:
            return

        text = sanitize_text(data.strip())
        if not text:
            return

        if self.current_tag == "title":
            self.title_parts.append(text)
        else:
            self.parts.append(text)

    def get_title(self, fallback: str) -> str:
        """title tag가 비어 있으면 URL 기반 fallback title을 반환한다."""
        title = " ".join(self.title_parts).strip()
        return normalize_whitespace(title) or fallback

    def get_text(self) -> str:
        """수집된 본문 조각을 공백 정규화된 plain text로 반환한다."""
        return normalize_text(" ".join(self.parts))


def sanitize_text(text: str) -> str:
    """Remove characters PostgreSQL text fields cannot safely store."""
    if not text:
        return ""
    text = text.replace("\x00", "")
    # Keep common whitespace but remove other C0 controls often produced by binary/PDF decoding.
    return "".join(ch for ch in text if ch in "\n\r\t" or ord(ch) >= 32)


def looks_like_binary_text(text: str) -> bool:
    """디코딩된 문자열이 PDF/바이너리처럼 깨졌는지 제어문자와 replacement 문자로 판단한다."""
    if not text:
        return False
    sample = text[:2000]
    control_count = sum(1 for ch in sample if ch not in "\n\r\t" and ord(ch) < 32)
    replacement_count = sample.count("�")
    return control_count > 10 or replacement_count > 20 or sample.startswith("%PDF")


def normalize_whitespace(text: str) -> str:
    """normalize_whitespace 함수. 비교/저장/출력을 안정화하기 위해 입력값 형식을 정규화한다."""
    return re.sub(r"\s+", " ", sanitize_text(text or "")).strip()


def normalize_text(text: str) -> str:
    """normalize_text 함수. 비교/저장/출력을 안정화하기 위해 입력값 형식을 정규화한다."""
    text = sanitize_text(text or "")
    lines = [normalize_whitespace(line) for line in re.split(r"[\r\n]+", text)]
    lines = [line for line in lines if line]
    joined = "\n".join(lines)
    joined = re.sub(r"\n{3,}", "\n\n", joined)
    return joined.strip()


def fetch_url_once(url: str, timeout: int = 15) -> tuple[str, str]:
    """공식 URL을 한 번 요청하고 body text와 content_type을 반환한다."""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "AX-Delivery-Planner/0.1 (+https://github.com/ohjaesik/AI_Agent)",
        },
    )

    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - user-provided official URL only
        raw = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        content_type = response.headers.get_content_type() or ""

    try:
        return raw.decode(charset), content_type
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="ignore"), content_type


def fetch_url(url: str, timeout: int = 15, retries: int = 2, backoff_seconds: float = 1.0) -> tuple[str, str]:
    """공식 URL 요청에 retry/backoff를 적용해 일시적 네트워크 실패를 완화한다."""
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
    """HTML title을 얻지 못했을 때 host/path로 사람이 알아볼 수 있는 제목을 만든다."""
    parsed = urlparse(url)
    host = parsed.netloc or "official-url"
    path = parsed.path.strip("/") or "home"
    return f"{host} {path}"


def is_pdf_or_binary_url(url: str, content_type: str, text: str) -> bool:
    """URL 확장자, content type, body 깨짐 정도로 HTML 추출 대상이 아닌지 판단한다."""
    lower_url = url.lower().split("?", 1)[0]
    lower_type = content_type.lower()
    return (
        lower_url.endswith(".pdf")
        or "application/pdf" in lower_type
        or (lower_type and "html" not in lower_type and "text" not in lower_type)
        or looks_like_binary_text(text)
    )


def load_official_url(url: str, max_chars: int = 20000) -> OfficialUrlDocument:
    """load_official_url 함수. 외부/DB/파일 입력을 읽어 workflow에서 사용할 구조로 적재한다."""
    html, content_type = fetch_url(url)
    fallback_title = fallback_title_from_url(url)

    if is_pdf_or_binary_url(url=url, content_type=content_type, text=html):
        return OfficialUrlDocument(
            url=url,
            title=fallback_title,
            content=PDF_PLACEHOLDER,
        )

    parser = ReadableHTMLParser()
    parser.feed(sanitize_text(html))

    title = parser.get_title(fallback=fallback_title)
    content = parser.get_text()

    if not content:
        content = normalize_text(re.sub(r"<[^>]+>", " ", html))

    if len(content) > max_chars:
        content = content[:max_chars] + "..."

    return OfficialUrlDocument(
        url=url,
        title=sanitize_text(title),
        content=sanitize_text(content),
    )
