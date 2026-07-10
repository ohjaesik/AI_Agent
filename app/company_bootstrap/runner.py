# app/company_bootstrap/runner.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.company_bootstrap.workflow import build_bootstrap_supervisor_graph
from app.core.config import get_settings


@dataclass(frozen=True)
class BootstrapGraphResult:
    company_id: int
    project_id: int | None
    document_ids: list[int]
    process_ids: list[int]
    chunk_count: int
    source_count: int
    warnings: list[str]
    discovery_mode: str | None = None
    workflow_mode: str = "bootstrap_supervisor_graph"
    idempotency: dict[str, Any] | None = None
    agent_trace: list[dict[str, Any]] | None = None
    agent_contracts: list[dict[str, Any]] | None = None
    agent_tool_calls: list[dict[str, Any]] | None = None
    agent_decisions: list[dict[str, Any]] | None = None
    agent_loop_iterations: list[dict[str, Any]] | None = None
    agent_loop_requests: list[dict[str, Any]] | None = None
    agent_llm_calls: list[dict[str, Any]] | None = None
    agent_model_decisions: list[dict[str, Any]] | None = None
    agent_supervisor_delegations: list[dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "company_id": self.company_id,
            "project_id": self.project_id,
            "document_ids": self.document_ids,
            "process_ids": self.process_ids,
            "chunk_count": self.chunk_count,
            "source_count": self.source_count,
            "warnings": self.warnings,
            "discovery_mode": self.discovery_mode,
            "workflow_mode": self.workflow_mode,
            "idempotency": self.idempotency or {},
            "agent_trace": self.agent_trace or [],
            "agent_contracts": self.agent_contracts or [],
            "agent_tool_calls": self.agent_tool_calls or [],
            "agent_decisions": self.agent_decisions or [],
            "agent_loop_iterations": self.agent_loop_iterations or [],
            "agent_loop_requests": self.agent_loop_requests or [],
            "agent_llm_calls": self.agent_llm_calls or [],
            "agent_model_decisions": self.agent_model_decisions or [],
            "agent_supervisor_delegations": self.agent_supervisor_delegations or [],
        }


def resolve_dart_api_key(explicit_key: str | None) -> str | None:
    if explicit_key:
        return explicit_key
    return get_settings().dart_api_key


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
    allow_agent_extra_loop: bool = False,
) -> BootstrapGraphResult:
    graph = build_bootstrap_supervisor_graph()
    initial_state = {
        "company_name": company_name,
        "official_urls": official_urls or [],
        "dart_api_key": resolve_dart_api_key(dart_api_key),
        "corp_code": corp_code,
        "stock_code": stock_code,
        "create_project": create_project,
        "index": index,
        "reset_company_chunks": reset_company_chunks,
        "warnings": [],
        "audit_logs": [],
        "agent_contracts": [],
        "agent_tool_calls": [],
        "agent_decisions": [],
        "agent_loop_iterations": [],
        "agent_loop_requests": [],
        "agent_llm_calls": [],
        "agent_model_decisions": [],
        "agent_supervisor_delegations": [],
        "agent_supervisor_extra_loop_enabled": allow_agent_extra_loop,
        "errors": [],
    }
    config = {"configurable": {"thread_id": thread_id}}
    result_state: dict[str, Any] = graph.invoke(initial_state, config=config)

    errors = result_state.get("errors", [])
    if errors:
        raise RuntimeError("Bootstrap Supervisor Graph failed: " + " | ".join(errors))

    payload = result_state.get("result") or {}
    warnings = list(result_state.get("warnings", []))

    return BootstrapGraphResult(
        company_id=int(payload.get("company_id")),
        project_id=payload.get("project_id"),
        document_ids=list(payload.get("document_ids", [])),
        process_ids=list(payload.get("process_ids", [])),
        chunk_count=int(payload.get("chunk_count", 0)),
        source_count=int(payload.get("source_count", 0)),
        warnings=warnings,
        discovery_mode=payload.get("discovery_mode"),
        workflow_mode="bootstrap_supervisor_graph",
        idempotency=payload.get("idempotency", {}),
        agent_trace=list(result_state.get("audit_logs", [])),
        agent_contracts=list(result_state.get("agent_contracts", [])),
        agent_tool_calls=list(result_state.get("agent_tool_calls", [])),
        agent_decisions=list(result_state.get("agent_decisions", [])),
        agent_loop_iterations=list(result_state.get("agent_loop_iterations", [])),
        agent_loop_requests=list(result_state.get("agent_loop_requests", [])),
        agent_llm_calls=list(result_state.get("agent_llm_calls", [])),
        agent_model_decisions=list(result_state.get("agent_model_decisions", [])),
        agent_supervisor_delegations=list(result_state.get("agent_supervisor_delegations", [])),
    )
