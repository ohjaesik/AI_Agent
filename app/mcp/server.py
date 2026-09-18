"""MCP server for the AX Delivery Planner.

Run locally:
  python -m app.mcp.server --transport stdio
  python -m app.mcp.server --transport streamable-http
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from app.core.config import get_settings
from app.mcp.adapter import (
    access_context_from_mcp,
    analysis_status,
    apply_review,
    bootstrap_company as bootstrap_company_adapter,
    ingest_text,
    report_resource,
    search_evidence,
    submit_analysis,
)

mcp = FastMCP(
    "AX Delivery Planner",
    instructions="Evidence-grounded manufacturing AX planning tools with role-aware governance.",
    host=get_settings().mcp_host,
    port=get_settings().mcp_port,
    streamable_http_path="/mcp",
    stateless_http=True,
)


@mcp.tool()
def search_evidence_tool(
    query: str,
    company_id: int,
    *,
    process_id: int | None = None,
    top_k: int = 5,
    ctx: Context,
) -> dict[str, Any]:
    """Search traceable RAG evidence visible to the current role."""
    access = access_context_from_mcp(ctx)
    return search_evidence(query=query, company_id=company_id, process_id=process_id, top_k=top_k, access=access)


@mcp.tool()
def run_delivery_analysis(
    *,
    project_id: int | None = None,
    company_id: int | None = None,
    auto_approve: bool = False,
    thread_id: str = "ax-planner-mcp",
    allow_agent_extra_loop: bool | None = None,
    supervisor_goal: str | None = None,
    ctx: Context,
) -> dict[str, Any]:
    """Queue an AX delivery analysis and return an analysis_id."""
    access = access_context_from_mcp(ctx)
    return submit_analysis(
        project_id=project_id,
        company_id=company_id,
        auto_approve=auto_approve,
        thread_id=thread_id,
        allow_agent_extra_loop=allow_agent_extra_loop,
        supervisor_goal=supervisor_goal,
        access=access,
    )


@mcp.tool()
def get_analysis_status(analysis_id: str, ctx: Context) -> dict[str, Any]:
    """Get queued/running/human_review/completed/failed analysis state."""
    return analysis_status(analysis_id)


@mcp.tool()
def bootstrap_company(
    company_name: str,
    *,
    official_urls: list[str] | None = None,
    corp_code: str | None = None,
    stock_code: str | None = None,
    create_project: bool = True,
    index: bool = True,
    reset_company_chunks: bool = False,
    thread_id: str = "bootstrap-supervisor-mcp",
    ctx: Context,
) -> dict[str, Any]:
    """Collect official company sources and discover candidate AX processes."""
    return bootstrap_company_adapter(
        company_name=company_name,
        official_urls=official_urls or [],
        dart_api_key=None,
        corp_code=corp_code,
        stock_code=stock_code,
        create_project=create_project,
        index=index,
        reset_company_chunks=reset_company_chunks,
        thread_id=thread_id,
        access=access_context_from_mcp(ctx),
    )


@mcp.tool()
def ingest_document_text(
    content: str,
    filename: str,
    company_id: int,
    *,
    process_id: int | None = None,
    title: str | None = None,
    document_type: str | None = None,
    department: str | None = None,
    security_level: str = "internal",
    allowed_roles: list[str] | None = None,
    index: bool = True,
    ctx: Context,
) -> dict[str, Any]:
    """Persist text content as a document and optionally index it."""
    access = access_context_from_mcp(ctx)
    return ingest_text(
        content=content, filename=filename, company_id=company_id, process_id=process_id,
        title=title, document_type=document_type, department=department,
        security_level=security_level, allowed_roles=allowed_roles, index=index, access=access,
    )


@mcp.tool()
def apply_human_review(
    priority_ranking: dict[str, Any],
    human_review: dict[str, Any],
    *,
    ctx: Context,
) -> dict[str, Any]:
    """Apply a manager/admin Human Review decision to the ranking."""
    access = access_context_from_mcp(ctx)
    return apply_review(priority_ranking=priority_ranking, human_review=human_review, access=access)


@mcp.resource("analysis://{analysis_id}/report", mime_type="application/json")
def get_report(analysis_id: str, ctx: Context) -> str:
    """Read the report summary for a completed analysis."""
    return report_resource(analysis_id)


@mcp.tool()
def get_report_tool(analysis_id: str, ctx: Context) -> dict[str, Any]:
    """Return the report resource payload as JSON for clients without resource support."""
    return json.loads(report_resource(analysis_id))


def main() -> None:
    parser = argparse.ArgumentParser(description="AX Delivery Planner MCP server")
    parser.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    args = parser.parse_args()
    if not get_settings().mcp_enabled:
        raise RuntimeError("MCP_ENABLED is false.")
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
