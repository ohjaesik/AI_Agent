# app/company_bootstrap/dart_client.py

"""OpenDART API client.

corp_code, stock_code, 회사명 기반으로 기업 개황과 공시 자료를 조회해 bootstrap
context에 사용할 공식 정보를 만든다.
"""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree

from app.core.retry import retry_call

DART_BASE_URL = "https://opendart.fss.or.kr/api"


@dataclass(frozen=True)
class DartCompany:
    """OpenDART에서 조회한 회사 식별자와 기업 개황 정보를 담는 값 객체다."""
    corp_code: str
    corp_name: str
    stock_code: str | None
    corp_cls: str | None
    profile: dict[str, Any]

    def to_document_content(self) -> str:
        """기업개황 profile을 RAG/업무발굴에 넣기 좋은 plain text 문서로 변환한다."""
        lines = [
            "OpenDART 기업개황",
            f"회사명: {self.profile.get('corp_name') or self.corp_name}",
            f"고유번호: {self.corp_code}",
            f"종목코드: {self.profile.get('stock_code') or self.stock_code or ''}",
            f"법인구분: {self.profile.get('corp_cls') or self.corp_cls or ''}",
            f"대표자명: {self.profile.get('ceo_nm', '')}",
            f"법인등록번호: {self.profile.get('jurir_no', '')}",
            f"사업자등록번호: {self.profile.get('bizr_no', '')}",
            f"주소: {self.profile.get('adres', '')}",
            f"홈페이지: {self.profile.get('hm_url', '')}",
            f"전화번호: {self.profile.get('phn_no', '')}",
            f"업종코드: {self.profile.get('induty_code', '')}",
            f"설립일: {self.profile.get('est_dt', '')}",
            f"결산월: {self.profile.get('acc_mt', '')}",
        ]
        return "\n".join(line for line in lines if line.strip())


def dart_get_json_once(endpoint: str, params: dict[str, str]) -> dict[str, Any]:
    """OpenDART JSON endpoint를 한 번 호출하고 응답 body를 dict로 파싱한다."""
    query = urllib.parse.urlencode(params)
    url = f"{DART_BASE_URL}/{endpoint}?{query}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "AX-Delivery-Planner/0.1"},
    )

    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed OpenDART endpoint
        raw = response.read().decode("utf-8", errors="ignore")

    return json.loads(raw)


def dart_get_json(endpoint: str, params: dict[str, str]) -> dict[str, Any]:
    """일시적 네트워크/API 오류에 retry를 적용해 OpenDART JSON을 조회한다."""
    return retry_call(
        lambda: dart_get_json_once(endpoint, params),
        retries=2,
        backoff_seconds=1.0,
        retry_exceptions=(TimeoutError, urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError),
    )


def download_corp_code_xml_once(api_key: str) -> bytes:
    """OpenDART corpCode.zip을 한 번 내려받아 내부 XML bytes를 꺼낸다."""
    query = urllib.parse.urlencode({"crtfc_key": api_key})
    url = f"{DART_BASE_URL}/corpCode.xml?{query}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "AX-Delivery-Planner/0.1"},
    )

    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - fixed OpenDART endpoint
        payload = response.read()

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        xml_names = [name for name in archive.namelist() if name.lower().endswith(".xml")]
        if not xml_names:
            raise ValueError("OpenDART corpCode response does not contain XML.")
        return archive.read(xml_names[0])


def download_corp_code_xml(api_key: str) -> bytes:
    """corpCode.xml 다운로드에 retry를 적용해 회사명 검색용 XML을 확보한다."""
    return retry_call(
        lambda: download_corp_code_xml_once(api_key),
        retries=2,
        backoff_seconds=1.0,
        retry_exceptions=(TimeoutError, urllib.error.URLError, urllib.error.HTTPError, zipfile.BadZipFile),
    )


def parse_corp_codes(xml_bytes: bytes) -> list[dict[str, str]]:
    """parse_corp_codes 함수. 문자열/파일/CLI 입력을 내부에서 쓰기 쉬운 구조로 파싱한다."""
    root = ElementTree.fromstring(xml_bytes)
    rows: list[dict[str, str]] = []

    for item in root.findall("list"):
        row = {
            "corp_code": (item.findtext("corp_code") or "").strip(),
            "corp_name": (item.findtext("corp_name") or "").strip(),
            "stock_code": (item.findtext("stock_code") or "").strip(),
            "modify_date": (item.findtext("modify_date") or "").strip(),
        }
        if row["corp_code"] and row["corp_name"]:
            rows.append(row)

    return rows


def find_corp_code(
    api_key: str,
    company_name: str,
    stock_code: str | None = None,
) -> dict[str, str] | None:
    """회사명 또는 종목코드로 OpenDART corp_code row를 찾는다."""
    rows = parse_corp_codes(download_corp_code_xml(api_key))
    normalized_name = company_name.replace(" ", "").lower()

    if stock_code:
        for row in rows:
            if row.get("stock_code") == stock_code:
                return row

    exact_matches = [
        row for row in rows
        if row.get("corp_name", "").replace(" ", "").lower() == normalized_name
    ]

    if exact_matches:
        listed = [row for row in exact_matches if row.get("stock_code")]
        return listed[0] if listed else exact_matches[0]

    contains_matches = [
        row for row in rows
        if normalized_name in row.get("corp_name", "").replace(" ", "").lower()
    ]

    if contains_matches:
        listed = [row for row in contains_matches if row.get("stock_code")]
        return listed[0] if listed else contains_matches[0]

    return None


def get_company_overview(
    api_key: str,
    corp_code: str,
) -> dict[str, Any]:
    """corp_code로 OpenDART 기업개황 company.json을 조회하고 오류 status를 검증한다."""
    data = dart_get_json(
        "company.json",
        {
            "crtfc_key": api_key,
            "corp_code": corp_code,
        },
    )

    status = data.get("status")
    if status and status != "000":
        raise ValueError(f"OpenDART company overview failed: {status} {data.get('message')}")

    return data


def load_dart_company(
    api_key: str,
    company_name: str,
    corp_code: str | None = None,
    stock_code: str | None = None,
) -> DartCompany | None:
    """load_dart_company 함수. 외부/DB/파일 입력을 읽어 workflow에서 사용할 구조로 적재한다."""
    corp_row: dict[str, str] | None

    if corp_code:
        corp_row = {
            "corp_code": corp_code,
            "corp_name": company_name,
            "stock_code": stock_code or "",
        }
    else:
        corp_row = find_corp_code(
            api_key=api_key,
            company_name=company_name,
            stock_code=stock_code,
        )

    if corp_row is None:
        return None

    profile = get_company_overview(
        api_key=api_key,
        corp_code=corp_row["corp_code"],
    )

    return DartCompany(
        corp_code=corp_row["corp_code"],
        corp_name=profile.get("corp_name") or corp_row.get("corp_name") or company_name,
        stock_code=profile.get("stock_code") or corp_row.get("stock_code") or None,
        corp_cls=profile.get("corp_cls"),
        profile=profile,
    )
