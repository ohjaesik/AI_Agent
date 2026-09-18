"""MCP gateway contracts and bounded job lifecycle tests."""

from __future__ import annotations

import os
import time

os.environ.setdefault("DATABASE_URL", "sqlite:///./mcp-test.db")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

from app.mcp.adapter import access_context, apply_review
from app.mcp.jobs import AnalysisJobRegistry
from app.mcp.server import mcp


def test_mcp_registers_business_tools_and_report_resource():
    names = set(mcp._tool_manager._tools)
    assert {"search_evidence_tool", "run_delivery_analysis", "get_analysis_status", "get_report_tool"} <= names
    assert any(getattr(route, "path", None) == "/mcp" for route in mcp.streamable_http_app().routes)


def test_analysis_job_completes():
    registry = AnalysisJobRegistry()
    analysis_id = registry.submit(lambda: {"status": "ok", "value": 3})
    deadline = time.time() + 2
    snapshot = registry.get(analysis_id)
    while snapshot and snapshot["status"] in {"queued", "running"} and time.time() < deadline:
        time.sleep(0.01)
        snapshot = registry.get(analysis_id)
    assert snapshot is not None
    assert snapshot["status"] == "completed"
    assert snapshot["result"] == {"status": "ok", "value": 3}


def test_human_review_requires_manager_or_admin():
    try:
        apply_review(priority_ranking={"items": []}, human_review={}, access=access_context(role="analyst"))
    except PermissionError as exc:
        assert "manager/admin" in str(exc)
    else:
        raise AssertionError("analyst must not apply Human Review")
