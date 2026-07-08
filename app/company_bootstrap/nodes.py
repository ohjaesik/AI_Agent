# app/company_bootstrap/nodes.py

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.company_bootstrap.dart_client import load_dart_company
from app.company_bootstrap.idempotency import (
    get_or_create_analysis_project,
    get_or_create_departments,
    get_or_create_systems,
    get_or_update_company,
    upsert_business_processes,
    upsert_source_documents,
)
from app.company_bootstrap.service import build_official_source_payloads, build_process_specs
from app.company_bootstrap.state import BootstrapState
from app.company_bootstrap.url_loader import load_official_url
from app.chains.company_process_discovery import discover_company_process_specs
from app.db.database import SessionLocal
from app.ingestion.service import index_single_document
from app.rag.indexer import delete_existing_chunks


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def audit(node_name: str, status: str, payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return [
        {
            "node": node_name,
            "status": status,
            "timestamp": utc_now(),
            "payload": payload or {},
        }
    ]


def error(node_name: str, exc: Exception) -> list[str]:
    return [f"[{node_name}] {type(exc).__name__}: {exc}"]


def company_profile_agent_node(state: BootstrapState) -> dict[str, Any]:
    node_name = "company_profile_agent"

    try:
        company_name = state["company_name"]
        dart_company = None
        warnings: list[str] = []

        if state.get("dart_api_key"):
            try:
                dart_company = load_dart_company(
                    api_key=str(state.get("dart_api_key")),
                    company_name=company_name,
                    corp_code=state.get("corp_code"),
                    stock_code=state.get("stock_code"),
                )
                if dart_company is None:
                    warnings.append("OpenDART에서 회사 고유번호를 찾지 못했습니다.")
            except Exception as exc:
                warnings.append(f"OpenDART 수집 실패: {type(exc).__name__}: {exc}")

        resolved_name = dart_company.corp_name if dart_company is not None else company_name
        dart_text = dart_company.to_document_content() if dart_company is not None else ""

        with SessionLocal() as db:
            company, created = get_or_update_company(
                db=db,
                company_name=resolved_name,
                combined_text=dart_text,
                dart_company=dart_company,
            )

        return {
            "dart_company": dart_company,
            "company_id": company.id,
            "resolved_company_name": company.name,
            "company_profile": {
                "id": company.id,
                "name": company.name,
                "industry": company.industry,
                "size": company.size,
                "description": company.description,
                "created": created,
            },
            "warnings": warnings,
            "audit_logs": audit(
                node_name,
                "success",
                {
                    "company_id": company.id,
                    "resolved_company_name": company.name,
                    "dart_collected": dart_company is not None,
                    "created": created,
                },
            ),
        }

    except Exception as exc:
        return {
            "errors": error(node_name, exc),
            "audit_logs": audit(node_name, "failed"),
        }


def source_ingestion_agent_node(state: BootstrapState) -> dict[str, Any]:
    node_name = "source_ingestion_agent"

    try:
        company_id = int(state["company_id"])
        dart_company = state.get("dart_company")
        official_urls = state.get("official_urls", []) or []
        warnings: list[str] = []
        official_docs = []

        for url in official_urls:
            try:
                official_docs.append(load_official_url(url))
            except Exception as exc:
                warnings.append(f"공식 URL 수집 실패: {url} ({type(exc).__name__}: {exc})")

        if dart_company is None and not official_docs:
            raise ValueError("No official source was collected. Provide --official-url or --dart-api-key.")

        combined_parts = []
        if dart_company is not None:
            combined_parts.append(dart_company.to_document_content())
        combined_parts.extend(doc.content for doc in official_docs)
        combined_text = "\n\n".join(combined_parts)

        with SessionLocal() as db:
            documents, created_count, updated_count = upsert_source_documents(
                db=db,
                company_id=company_id,
                official_docs=official_docs,
                dart_company=dart_company,
            )

            chunk_count = 0
            if state.get("index", True):
                if state.get("reset_company_chunks", False):
                    delete_existing_chunks(db, company_id=company_id)
                for document in documents:
                    chunk_count += index_single_document(db=db, document=document, reset_existing=True)

        official_sources = build_official_source_payloads(
            official_docs=official_docs,
            dart_company=dart_company,
        )

        return {
            "official_docs": official_docs,
            "combined_text": combined_text,
            "official_sources": official_sources,
            "document_ids": [document.id for document in documents],
            "chunk_count": chunk_count,
            "source_count": len(documents),
            "warnings": warnings,
            "audit_logs": audit(
                node_name,
                "success",
                {
                    "official_url_count": len(official_docs),
                    "document_count": len(documents),
                    "created_documents": created_count,
                    "updated_documents": updated_count,
                    "chunk_count": chunk_count,
                },
            ),
        }

    except Exception as exc:
        return {
            "errors": error(node_name, exc),
            "audit_logs": audit(node_name, "failed"),
        }


def process_discovery_agent_node(state: BootstrapState) -> dict[str, Any]:
    node_name = "process_discovery_agent"

    try:
        company_id = int(state["company_id"])
        company_name = str(state.get("resolved_company_name") or state.get("company_name"))
        combined_text = state.get("combined_text", "")
        official_sources = state.get("official_sources", [])
        warnings: list[str] = []

        fallback_process_specs = build_process_specs(combined_text)
        discovered_process_specs = discover_company_process_specs(
            company_name=company_name,
            official_sources=official_sources,
            fallback_processes=fallback_process_specs,
        )

        discovery_mode = discovered_process_specs[0].get("discovery_mode") if discovered_process_specs else None
        discovery_warning = discovered_process_specs[0].get("discovery_warning") if discovered_process_specs else None
        if discovery_warning:
            warnings.append(discovery_warning)

        with SessionLocal() as db:
            departments, created_departments = get_or_create_departments(db, company_id=company_id)
            _, created_systems = get_or_create_systems(db, company_id=company_id)
            processes, created_processes, updated_processes = upsert_business_processes(
                db=db,
                company_id=company_id,
                departments=departments,
                process_specs=discovered_process_specs,
            )
            project = None
            project_created = False
            if state.get("create_project", True):
                project, project_created = get_or_create_analysis_project(
                    db,
                    company_id=company_id,
                    company_name=company_name,
                )

        result = {
            "company_id": company_id,
            "project_id": project.id if project else None,
            "document_ids": state.get("document_ids", []),
            "process_ids": [process.id for process in processes],
            "chunk_count": int(state.get("chunk_count", 0)),
            "source_count": int(state.get("source_count", 0)),
            "warnings": warnings,
            "discovery_mode": discovery_mode,
            "workflow_mode": "bootstrap_supervisor_graph",
            "idempotency": {
                "created_departments": created_departments,
                "created_systems": created_systems,
                "created_processes": created_processes,
                "updated_processes": updated_processes,
                "project_created": project_created,
            },
        }

        return {
            "process_specs": discovered_process_specs,
            "process_ids": [process.id for process in processes],
            "project_id": project.id if project else None,
            "discovery_mode": discovery_mode,
            "warnings": warnings,
            "result": result,
            "audit_logs": audit(
                node_name,
                "success",
                {
                    "process_count": len(processes),
                    "created_processes": created_processes,
                    "updated_processes": updated_processes,
                    "project_id": project.id if project else None,
                    "project_created": project_created,
                    "discovery_mode": discovery_mode,
                },
            ),
        }

    except Exception as exc:
        return {
            "errors": error(node_name, exc),
            "audit_logs": audit(node_name, "failed"),
        }
