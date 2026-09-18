"""Small, JSON-safe contracts shared by MCP tools and jobs."""

from __future__ import annotations

from typing import Any, Literal, TypedDict


JobStatus = Literal["queued", "running", "human_review", "completed", "failed"]


class JobSnapshot(TypedDict):
    analysis_id: str
    status: JobStatus
    created_at: str
    updated_at: str
    result: dict[str, Any] | None
    error: str | None
    owner_user_id: str
    company_id: int | None
    project_id: int | None
