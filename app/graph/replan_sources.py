# app/graph/replan_sources.py
"""근거 보강 replan에서 사용할 공식/외부 출처를 수집하고 색인한다."""

from __future__ import annotations

from typing import Any

from app.company_bootstrap.idempotency import upsert_source_documents
from app.company_bootstrap.public_web_search import discover_public_web_sources
from app.company_bootstrap.source_discovery import discover_official_sources
from app.company_bootstrap.url_loader import load_official_url
from app.core.config import get_settings
from app.db.database import SessionLocal
from app.ingestion.service import index_single_document


def official_seed_urls(state: dict[str, Any]) -> tuple[list[str], set[str]]:
    """used_sources/documents에서 같은 공식 도메인 탐색에 쓸 seed URL을 만든다."""

    seed_urls: list[str] = []
    existing_urls: set[str] = set()

    for source in state.get("used_sources", []) or []:
        url = source.get("url") or source.get("source_url")
        if isinstance(url, str) and url.startswith("http"):
            seed_urls.append(url)
            existing_urls.add(url)

    for document in state.get("documents", []) or []:
        url = document.get("source_url") or document.get("url")
        if isinstance(url, str) and url.startswith("http"):
            seed_urls.append(url)
            existing_urls.add(url)

    deduped = []
    seen = set()
    for url in seed_urls:
        if url in seen:
            continue
        seen.add(url)
        deduped.append(url)
    return deduped, existing_urls


def replan_query_terms(state: dict[str, Any], replan_items: list[dict[str, Any]]) -> list[str]:
    """replan 대상 후보에서 public search query term을 뽑아 중복 제거한다."""

    terms: list[str] = []
    for item in replan_items:
        for key in ("process_name", "candidate_agent_name"):
            value = item.get(key)
            if value:
                terms.append(str(value))
        terms.extend(str(value) for value in item.get("requery_terms", []) if value)
    company = state.get("company_profile", {}) or {}
    if company.get("name"):
        terms.append(str(company["name"]))
    seen = set()
    deduped = []
    for term in terms:
        normalized = term.strip()
        if not normalized or normalized.lower() in seen:
            continue
        seen.add(normalized.lower())
        deduped.append(normalized)
    return deduped[:12]


def has_replan_source_path(state: dict[str, Any]) -> bool:
    """자동 replan이 사용할 seed URL 또는 external discovery 옵션이 있는지 확인한다."""

    settings = get_settings()
    seed_urls, _ = official_seed_urls(state)
    return bool(seed_urls) or bool(settings.external_web_discovery_enabled)


def collect_discovered_sources(state: dict[str, Any], replan_items: list[dict[str, Any]], max_total: int = 3) -> dict[str, Any]:
    """공식 도메인/선택적 public search 결과를 로드하고 신규 문서를 색인한다."""

    settings = get_settings()
    company_id = int(state["company_id"])
    company_name = str((state.get("company_profile", {}) or {}).get("name") or "")
    seed_urls, existing_urls = official_seed_urls(state)
    warnings: list[str] = []

    official_discovered = []
    if seed_urls:
        official_discovered = discover_official_sources(seed_urls=seed_urls, existing_urls=existing_urls, max_total=max_total)
    else:
        warnings.append("No official seed URL available for same-domain discovery.")

    public_search = discover_public_web_sources(
        company_name=company_name,
        query_terms=replan_query_terms(state, replan_items),
        existing_urls=existing_urls,
        max_results=settings.external_web_max_results,
    )

    urls_to_load: list[dict[str, str]] = []
    for item in official_discovered:
        urls_to_load.append({"url": item.url, "source_kind": "same_domain_official", "reason": item.reason})
    for item in public_search.get("results", []):
        urls_to_load.append({"url": str(item.get("url")), "source_kind": "external_public_web", "reason": str(item.get("provider", "public_web_search"))})

    loaded_docs = []
    for item in urls_to_load:
        try:
            loaded_docs.append(load_official_url(item["url"]))
        except Exception as exc:
            warnings.append(f"URL 자동 수집 실패: {item['url']} ({type(exc).__name__}: {exc})")

    created_count = 0
    updated_count = 0
    indexed_chunks = 0
    document_ids: list[int] = []
    with SessionLocal() as db:
        if loaded_docs:
            documents, created_count, updated_count = upsert_source_documents(
                db=db,
                company_id=company_id,
                official_docs=loaded_docs,
                dart_company=None,
            )
            for document in documents:
                document_ids.append(int(document.id))
                indexed_chunks += index_single_document(db=db, document=document, reset_existing=True)

    return {
        "same_domain_discovered": [item.to_dict() for item in official_discovered],
        "public_web_search": public_search,
        "loaded": [{"url": doc.url, "title": doc.title} for doc in loaded_docs],
        "document_ids": document_ids,
        "created_documents": created_count,
        "updated_documents": updated_count,
        "indexed_chunks": indexed_chunks,
        "warnings": [*warnings, *public_search.get("warnings", [])],
    }
