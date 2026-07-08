# app/graph/replan_node.py

from __future__ import annotations

from typing import Any

from app.agents.tool_guard import assert_tools_allowed
from app.company_bootstrap.idempotency import upsert_source_documents
from app.company_bootstrap.source_discovery import discover_official_sources
from app.company_bootstrap.url_loader import load_official_url
from app.db.crud import save_analysis_result, write_audit_log
from app.db.database import SessionLocal
from app.ingestion.service import index_single_document
from app.graph.nodes import append_audit, append_error
from app.graph.state import AXPlannerState


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
    return items


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


def collect_discovered_sources(state: AXPlannerState, max_total: int = 3) -> dict[str, Any]:
    company_id = int(state["company_id"])
    seed_urls, existing_urls = official_seed_urls(state)
    if not seed_urls:
        return {"discovered": [], "loaded": [], "created_documents": 0, "updated_documents": 0, "indexed_chunks": 0, "warnings": ["No official seed URL available for discovery."]}

    discovered = discover_official_sources(seed_urls=seed_urls, existing_urls=existing_urls, max_total=max_total)
    loaded_docs = []
    warnings: list[str] = []
    for item in discovered:
        try:
            loaded_docs.append(load_official_url(item.url))
        except Exception as exc:
            warnings.append(f"공식 URL 자동 수집 실패: {item.url} ({type(exc).__name__}: {exc})")

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
        "discovered": [item.to_dict() for item in discovered],
        "loaded": [{"url": doc.url, "title": doc.title} for doc in loaded_docs],
        "document_ids": document_ids,
        "created_documents": created_count,
        "updated_documents": updated_count,
        "indexed_chunks": indexed_chunks,
        "warnings": warnings,
    }


def should_replan(state: AXPlannerState) -> str:
    attempts = int(state.get("replan_attempts", 0) or 0)
    if attempts >= 1:
        return "human_review"

    evaluation = state.get("agent_evaluation", {}) or {}
    summary = evaluation.get("summary", {}) or {}
    if int(summary.get("additional_evidence_required_count", 0) or 0) > 0:
        return "agent_replan"
    return "human_review"


def agent_replan_node(state: AXPlannerState) -> dict[str, Any]:
    node_name = "agent_replan"

    try:
        assert_tools_allowed(
            "agent_evaluator_agent",
            ["agent evaluator", "evidence coverage scorer", "analysis result writer"],
        )
        attempts = int(state.get("replan_attempts", 0) or 0) + 1
        replan_items = build_replan_items(state)
        source_collection = collect_discovered_sources(state, max_total=3)
        replan_request = {
            "attempt": attempts,
            "mode": "official_url_discovery_plus_rag_requery",
            "reason": "Agent Evaluator가 일부 후보의 근거 coverage 또는 confidence 부족을 감지했다.",
            "items": replan_items,
            "source_collection": source_collection,
            "note": "현재 graph는 같은 공식 도메인의 sitemap/link 기반 추가 URL을 최대 3개 자동 수집하고 RAG에 색인한다. 내부 문서 업로드나 인터뷰 메모는 Human Review/API 입력이 필요하다.",
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
                    "replan_item_count": len(replan_items),
                    "discovered_url_count": len(source_collection.get("discovered", [])),
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
                    "replan_item_count": len(replan_items),
                    "discovered_url_count": len(source_collection.get("discovered", [])),
                    "indexed_chunks": source_collection.get("indexed_chunks", 0),
                },
            ),
        }

    except Exception as exc:
        return {
            "errors": append_error(state, node_name, exc),
            "audit_logs": append_audit(state, node_name, "failed"),
        }
