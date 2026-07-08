# app/company_bootstrap/runner.py

from __future__ import annotations

from typing import Any

from app.company_bootstrap.service import BootstrapResult
from app.company_bootstrap.workflow import build_bootstrap_supervisor_graph


def run_bootstrap_supervisor_graph(
    company_name: str,
    official_urls: list[str] | None = None,
    dart_api_key: str | None = None,
    corp_code: str | None = None,
    stock_code: str | None = None,
    create_project: bool = True,
    index: bool = True,
    reset_company_chunks: bool = False,
    thread_id: str = "bootstrap-supervisor-cli",
) -> BootstrapResult:
    graph = build_bootstrap_supervisor_graph()
    initial_state = {
        "company_name": company_name,
        "official_urls": official_urls or [],
        "dart_api_key": dart_api_key,
        "corp_code": corp_code,
        "stock_code": stock_code,
        "create_project": create_project,
        "index": index,
        "reset_company_chunks": reset_company_chunks,
        "warnings": [],
        "audit_logs": [],
        "errors": [],
    }
    config = {"configurable": {"thread_id": thread_id}}
    result_state: dict[str, Any] = graph.invoke(initial_state, config=config)

    errors = result_state.get("errors", [])
    if errors:
        raise RuntimeError("Bootstrap Supervisor Graph failed: " + " | ".join(errors))

    payload = result_state.get("result") or {}
    warnings = list(result_state.get("warnings", []))

    return BootstrapResult(
        company_id=int(payload.get("company_id")),
        project_id=payload.get("project_id"),
        document_ids=list(payload.get("document_ids", [])),
        process_ids=list(payload.get("process_ids", [])),
        chunk_count=int(payload.get("chunk_count", 0)),
        source_count=int(payload.get("source_count", 0)),
        warnings=warnings,
        discovery_mode=payload.get("discovery_mode"),
        workflow_mode="bootstrap_supervisor_graph",
        agent_trace=list(result_state.get("audit_logs", [])),
    )
