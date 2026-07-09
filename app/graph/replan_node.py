# app/graph/replan_node.py

from __future__ import annotations

from typing import Any

from app.agents.tool_guard import assert_tools_allowed
from app.company_bootstrap.idempotency import upsert_source_documents
from app.company_bootstrap.public_web_search import discover_public_web_sources
from app.company_bootstrap.source_discovery import discover_official_sources
from app.company_bootstrap.url_loader import load_official_url
from app.core.config import get_settings
from app.db.crud import save_analysis_result, write_audit_log
from app.db.database import SessionLocal
from app.graph.nodes import append_audit, append_error
from app.graph.state import AXPlannerState
from app.ingestion.service import index_single_document


REPLAN_MAX_ITEMS = 5


def build_replan_items(state: AXPlannerState) -> list[dict[str, Any]]:
    items = []
    ranking_items = {int(item.get("process_id") or 0): item for item in state.get("priority_ranking", {}).get("items", [])}

    for evaluation in state.get("agent_evaluation", {}).get("items", []):
        if not evaluation.get("requires_additional_evidence"):
            continue
        process_id = int(evaluation.get("process_id") or 0)
        candidate = ranking_items.get(process_id, {})
        items.append(
            {
                "process_id": process_id,
                "candidate_agent_name": evaluation.get("candidate_agent_name") or candidate.get("candidate_agent_name"),
                "process_name": candidate.get("process_name"),
                "evidence_coverage": evaluation.get("evidence_coverage"),
                "confidence_score": evaluation.get("confidence_score"),
                "issues": evaluation.get("issues", []),
                "suggested_actions": [
                    "관련 공식 URL 자동 탐색 및 수집",
                    "옵션 활성화 시 public web search 기반 보조 출처 탐색",
                    "업무 매뉴얼 또는 내부 규정 문서 업로드",
                    "해당 업무 owner 인터뷰 메모 추가",
                    "RAG 재색인 후 재평가",
                ],
                "requery_terms": [
                    candidate.get("process_name"),
                    candidate.get("candidate_agent_name"),
                    candidate.get("target_user"),
                    "업무 절차",
                    "규정",
                    "SOP",
                ],
            }
        )
    return items[:REPLAN_MAX_ITEMS]


def official_seed_urls(state: AXPlannerState) -> tuple[list[str], set[str]]:
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


def replan_query_terms(state: AXPlannerState, replan_items: list[dict[str, Any]]) -> list[str]:
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


def collect_discovered_sources(state: AXPlannerState, replan_items: list[dict[str, Any]], max_total: int = 3) -> dict[str, Any]:
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


def has_additional_evidence_need(state: AXPlannerState) -> bool:
    evaluation = state.get("agent_evaluation", {}) or {}
    summary = evaluation.get("summary", {}) or {}
    return int(summary.get("additional_evidence_required_count", 0) or 0) > 0


def has_replan_source_path(state: AXPlannerState) -> bool:
    settings = get_settings()
    seed_urls, _ = official_seed_urls(state)
    return bool(seed_urls) or bool(settings.external_web_discovery_enabled)


def previous_replan_unproductive(state: AXPlannerState) -> bool:
    if int(state.get("replan_attempts", 0) or 0) <= 0:
        return False

    source_collection = (state.get("replan_request") or {}).get("source_collection") or {}
    same_domain = source_collection.get("same_domain_discovered") or []
    public_results = ((source_collection.get("public_web_search") or {}).get("results") or [])
    loaded = source_collection.get("loaded") or []
    indexed_chunks = int(source_collection.get("indexed_chunks") or 0)

    return not same_domain and not public_results and not loaded and indexed_chunks <= 0


def replan_route_reason(state: AXPlannerState) -> str:
    settings = get_settings()
    attempts = int(state.get("replan_attempts", 0) or 0)
    max_attempts = max(int(settings.agent_replan_max_attempts or 0), 0)

    if max_attempts <= 0:
        return "replan_disabled"
    if attempts >= max_attempts:
        return "max_replan_attempts_reached"
    if not has_additional_evidence_need(state):
        return "no_additional_evidence_needed"
    if previous_replan_unproductive(state):
        return "previous_replan_unproductive"
    if not has_replan_source_path(state):
        return "no_replan_source_path"
    return "route_to_replan"


def should_replan(state: AXPlannerState) -> str:
    return "agent_replan" if replan_route_reason(state) == "route_to_replan" else "human_review"


def agent_replan_node(state: AXPlannerState) -> dict[str, Any]:
    node_name = "agent_replan"

    try:
        assert_tools_allowed(
            "agent_evaluator_agent",
            ["agent evaluator", "evidence coverage scorer", "analysis result writer"],
        )
        attempts = int(state.get("replan_attempts", 0) or 0) + 1
        replan_items = build_replan_items(state)
        source_collection = collect_discovered_sources(state, replan_items=replan_items, max_total=3)
        replan_request = {
            "attempt": attempts,
            "max_attempts": max(int(get_settings().agent_replan_max_attempts or 0), 0),
            "mode": "official_domain_plus_opt_in_public_web_discovery",
            "reason": "Agent Evaluator가 일부 후보의 근거 coverage 또는 confidence 부족을 감지했다.",
            "items": replan_items,
            "source_collection": source_collection,
            "note": "동일 공식 도메인의 sitemap/link 기반 URL을 자동 수집한다. EXTERNAL_WEB_DISCOVERY_ENABLED=true이면 Brave/SerpAPI 기반 public web search 결과도 보조 출처로 수집한다. 내부 문서 업로드나 인터뷰 메모는 Human Review/API 입력이 필요하다.",
        }

        with SessionLocal() as db:
            save_analysis_result(
                db=db,
                project_id=int(state["project_id"]),
                node_name=node_name,
                result_json=replan_request,
            )
            write_audit_log(
                db=db,
                project_id=int(state["project_id"]),
                node_name=node_name,
                event_type="success",
                payload={
                    "attempt": attempts,
                    "max_attempts": replan_request["max_attempts"],
                    "replan_item_count": len(replan_items),
                    "same_domain_url_count": len(source_collection.get("same_domain_discovered", [])),
                    "public_web_url_count": len(source_collection.get("public_web_search", {}).get("results", [])),
                    "indexed_chunks": source_collection.get("indexed_chunks", 0),
                },
            )

        return {
            "replan_attempts": attempts,
            "replan_request": replan_request,
            "audit_logs": append_audit(
                state,
                node_name,
                "success",
                payload={
                    "attempt": attempts,
                    "max_attempts": replan_request["max_attempts"],
                    "replan_item_count": len(replan_items),
                    "same_domain_url_count": len(source_collection.get("same_domain_discovered", [])),
                    "public_web_url_count": len(source_collection.get("public_web_search", {}).get("results", [])),
                    "indexed_chunks": source_collection.get("indexed_chunks", 0),
                },
            ),
        }

    except Exception as exc:
        return {
            "errors": append_error(state, node_name, exc),
            "audit_logs": append_audit(state, node_name, "failed"),
        }
