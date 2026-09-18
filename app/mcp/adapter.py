"""MCP adapters that delegate to existing API/service/runtime implementations."""

from __future__ import annotations

import json
import secrets
import tempfile
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context

from app.api.responses import build_analysis_response
from app.api.security import decode_access_token, normalize_role, validate_api_key
from app.agents.tool_runtime import ToolCallResult, call_agent_tool
from app.company_bootstrap.runner import run_bootstrap_supervisor_graph
from app.db.database import SessionLocal
from app.ingestion.service import ingest_file
from app.main import DEFAULT_STATE_OUTPUT_PATH, run_demo
from app.rag.retriever import search_similar_chunks
from app.security.access_control import AccessContext
from app.tools.review_applier import apply_human_review_to_ranking

from app.mcp.jobs import AnalysisJobBackend, jobs


def access_context(
    *,
    auth_token: str | None = None,
    api_key: str | None = None,
    user_id: str = "mcp-user",
    role: str = "analyst",
) -> AccessContext:
    """Apply the same JWT/API-key rules as the HTTP API."""
    from app.core.config import get_settings

    if auth_token:
        return decode_access_token(auth_token)
    expected_mcp_token = get_settings().mcp_auth_token
    if expected_mcp_token:
        if not api_key or not secrets.compare_digest(api_key, expected_mcp_token):
            raise PermissionError("Invalid or missing MCP auth token.")
        return AccessContext(user_id=user_id, role=normalize_role(role))
    validate_api_key(api_key)
    return AccessContext(user_id=user_id, role=normalize_role(role))


def access_context_from_mcp(ctx: Context) -> AccessContext:
    """Build identity from transport metadata, never from tool arguments."""
    request = getattr(getattr(ctx, "request_context", None), "request", None)
    headers = getattr(request, "headers", {}) or {}
    authorization = headers.get("authorization", "")
    token = authorization.removeprefix("Bearer ").strip() or None
    return access_context(
        auth_token=token,
        api_key=headers.get("x-api-key"),
        user_id=headers.get("x-user-id", "mcp-user"),
        role=headers.get("x-user-role", "analyst"),
    )


def _summary(result: dict[str, Any], access: AccessContext) -> dict[str, Any]:
    return build_analysis_response(result=result, access=access)


def _runtime_payload(call: ToolCallResult) -> dict[str, Any]:
    """Preserve the common runtime audit trace in every MCP response."""
    result = dict(call.result)
    result["audit_logs"] = call.audit_logs
    result["observation"] = call.observation
    return result


def search_evidence(
    *,
    query: str,
    company_id: int,
    process_id: int | None = None,
    top_k: int = 5,
    access: AccessContext,
) -> dict[str, Any]:
    if not query.strip():
        raise ValueError("query must not be empty")
    bounded_top_k = min(max(top_k, 1), 20)
    def tool_runner(payload: dict[str, Any]) -> dict[str, Any]:
        with SessionLocal() as db:
            results = search_similar_chunks(
                db=db,
                query=payload["query"],
                company_id=payload["company_id"],
                process_id=payload["process_id"],
                top_k=payload["top_k"],
                user_role=payload["role"],
            )
        return {
            "status": "ok",
            "query": query,
            "company_id": company_id,
            "process_id": process_id,
            "count": len(results),
            "results": results,
        }

    return _runtime_payload(call_agent_tool(
        agent_id="mcp_gateway_agent",
        tool_name="mcp_search_evidence",
        payload={"query": query, "company_id": company_id, "process_id": process_id, "top_k": bounded_top_k, "role": access.role},
        runner=tool_runner,
        node_name="mcp_gateway",
        write_scopes=["mcp.audit"],
        read_scopes=["company.metadata"],
        network_policy="none",
    ))


def submit_analysis(
    *,
    project_id: int | None,
    company_id: int | None,
    auto_approve: bool,
    thread_id: str,
    allow_agent_extra_loop: bool | None,
    supervisor_goal: str | None,
    access: AccessContext,
    job_backend: AnalysisJobBackend = jobs,
) -> dict[str, Any]:
    def runner() -> dict[str, Any]:
        result = run_demo(
            project_id=project_id,
            company_id=company_id,
            thread_id=thread_id,
            auto_approve=auto_approve,
            verbose=False,
            state_output_path=DEFAULT_STATE_OUTPUT_PATH,
            allow_agent_extra_loop=allow_agent_extra_loop,
            supervisor_goal=supervisor_goal,
        )
        return _summary(result, access)

    def enqueue(_: dict[str, Any]) -> dict[str, Any]:
        return {"status": "queued", "analysis_id": job_backend.submit(runner)}

    return _runtime_payload(call_agent_tool(
        agent_id="mcp_gateway_agent",
        tool_name="mcp_run_delivery_analysis",
        payload={"project_id": project_id, "company_id": company_id, "thread_id": thread_id},
        runner=enqueue,
        node_name="mcp_gateway",
        write_scopes=["mcp.job", "mcp.audit"],
        read_scopes=["project.metadata", "company.metadata"],
        network_policy="delegated_only",
    ))


def bootstrap_company(
    *,
    company_name: str,
    official_urls: list[str],
    dart_api_key: str | None,
    corp_code: str | None,
    stock_code: str | None,
    create_project: bool,
    index: bool,
    reset_company_chunks: bool,
    thread_id: str,
    access: AccessContext,
) -> dict[str, Any]:
    def tool_runner(_: dict[str, Any]) -> dict[str, Any]:
        result = run_bootstrap_supervisor_graph(
            company_name=company_name,
            official_urls=official_urls,
            dart_api_key=dart_api_key,
            corp_code=corp_code,
            stock_code=stock_code,
            create_project=create_project,
            index=index,
            reset_company_chunks=reset_company_chunks,
            thread_id=thread_id,
        )
        return {"status": "ok", "result": result.to_dict()}

    return _runtime_payload(call_agent_tool(
        agent_id="mcp_gateway_agent",
        tool_name="mcp_bootstrap_company",
        payload={"company_name": company_name, "official_urls": official_urls},
        runner=tool_runner,
        node_name="mcp_gateway",
        write_scopes=["mcp.audit"],
        read_scopes=["company.metadata"],
        network_policy="delegated_only",
    ))


def analysis_status(analysis_id: str, job_backend: AnalysisJobBackend = jobs) -> dict[str, Any]:
    snapshot = job_backend.get(analysis_id)
    if not snapshot:
        raise KeyError(f"Unknown analysis_id: {analysis_id}")
    return snapshot


def report_resource(analysis_id: str, job_backend: AnalysisJobBackend = jobs) -> str:
    snapshot = analysis_status(analysis_id, job_backend=job_backend)
    if snapshot["status"] not in {"completed", "human_review"} or not snapshot["result"]:
        return json.dumps({"analysis_id": analysis_id, "status": snapshot["status"]}, ensure_ascii=False)
    result = snapshot["result"]
    return json.dumps(
        {
            "analysis_id": analysis_id,
            "report_data": result.get("report_data", {}),
            "report_docx_path": result.get("report_docx_path"),
        },
        ensure_ascii=False,
        default=str,
    )


def apply_review(*, priority_ranking: dict[str, Any], human_review: dict[str, Any], access: AccessContext) -> dict[str, Any]:
    if access.role not in {"manager", "admin"}:
        raise PermissionError("Only manager/admin role can apply human review decisions.")
    def tool_runner(_: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "ok",
            "priority_ranking": apply_human_review_to_ranking(
                priority_ranking=priority_ranking,
                human_review=human_review,
            ),
        }

    return _runtime_payload(call_agent_tool(
        agent_id="mcp_gateway_agent",
        tool_name="mcp_apply_human_review",
        payload={"priority_ranking": priority_ranking, "human_review": human_review},
        runner=tool_runner,
        node_name="mcp_gateway",
        write_scopes=["mcp.audit"],
        read_scopes=["priority_ranking"],
        network_policy="none",
        approval_requirements=["business_operation"],
        approval_context={"business_operation": access.role in {"manager", "admin"}},
    ))


def ingest_text(
    *,
    content: str,
    filename: str,
    company_id: int,
    process_id: int | None,
    title: str | None,
    document_type: str | None,
    department: str | None,
    security_level: str,
    allowed_roles: list[str] | None,
    index: bool,
    access: AccessContext,
) -> dict[str, Any]:
    if not content.strip():
        raise ValueError("content must not be empty")
    suffix = Path(filename).suffix or ".txt"
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, mode="w", encoding="utf-8") as handle:
            temp_path = Path(handle.name)
            handle.write(content)
        def tool_runner(_: dict[str, Any]) -> dict[str, Any]:
            with SessionLocal() as db:
                result = ingest_file(
                    db=db,
                    file_path=temp_path,
                    company_id=company_id,
                    process_id=process_id,
                    title=title or Path(filename).stem,
                    document_type=document_type,
                    department=department,
                    security_level=security_level,
                    allowed_roles=allowed_roles,
                    uploaded_by_user_id=access.user_id,
                    index=index,
                )
            return {"status": "ok", "result": result.to_dict()}

        return _runtime_payload(call_agent_tool(
            agent_id="mcp_gateway_agent",
            tool_name="mcp_ingest_document",
            payload={"company_id": company_id, "filename": filename, "security_level": security_level},
            runner=tool_runner,
            node_name="mcp_gateway",
            write_scopes=["mcp.audit"],
            read_scopes=["company.metadata", "documents.metadata"],
            network_policy="none",
        ))
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)
