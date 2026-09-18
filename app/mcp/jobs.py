"""Bounded in-memory analysis jobs used by the MCP interface.

The graph itself remains the source of truth. This registry only prevents a long
running MCP request from holding an HTTP connection and is intentionally replaceable
with a durable queue in production.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable, Protocol
from uuid import uuid4

from app.core.config import get_settings
from app.mcp.schemas import JobSnapshot, JobStatus


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AnalysisJobBackend(Protocol):
    """Durable storage/queue contract used by the MCP adapter."""

    def submit(self, runner: Callable[[], dict[str, Any]]) -> str: ...
    def get(self, analysis_id: str) -> JobSnapshot | None: ...


class InMemoryAnalysisJobBackend:
    def __init__(self) -> None:
        settings = get_settings()
        self._max_jobs = max(1, settings.mcp_max_jobs)
        self._ttl_seconds = max(60, settings.mcp_job_ttl_seconds)
        self._executor = ThreadPoolExecutor(max_workers=min(4, self._max_jobs), thread_name_prefix="mcp-analysis")
        self._jobs: dict[str, JobSnapshot] = {}
        self._lock = threading.RLock()

    def submit(self, runner: Callable[[], dict[str, Any]]) -> str:
        with self._lock:
            self._prune()
            active = sum(item["status"] in {"queued", "running"} for item in self._jobs.values())
            if active >= self._max_jobs:
                raise RuntimeError("MCP analysis job capacity is full.")
            analysis_id = f"analysis-{uuid4()}"
            now = _now()
            self._jobs[analysis_id] = {
                "analysis_id": analysis_id,
                "status": "queued",
                "created_at": now,
                "updated_at": now,
                "result": None,
                "error": None,
            }
        self._executor.submit(self._run, analysis_id, runner)
        return analysis_id

    def _run(self, analysis_id: str, runner: Callable[[], dict[str, Any]]) -> None:
        self._update(analysis_id, status="running")
        try:
            result = runner()
            status: JobStatus = "human_review" if "__interrupt__" in result else "completed"
            self._update(analysis_id, status=status, result=result)
        except Exception as exc:
            self._update(analysis_id, status="failed", error=f"{type(exc).__name__}: {exc}")

    def _update(self, analysis_id: str, **changes: Any) -> None:
        with self._lock:
            if analysis_id in self._jobs:
                self._jobs[analysis_id] = {**self._jobs[analysis_id], **changes, "updated_at": _now()}

    def get(self, analysis_id: str) -> JobSnapshot | None:
        with self._lock:
            self._prune()
            snapshot = self._jobs.get(analysis_id)
            return dict(snapshot) if snapshot else None

    def _prune(self) -> None:
        now = datetime.now(timezone.utc).timestamp()
        expired = [
            key for key, item in self._jobs.items()
            if now - datetime.fromisoformat(item["updated_at"]).timestamp() > self._ttl_seconds
            and item["status"] not in {"queued", "running"}
        ]
        for key in expired:
            self._jobs.pop(key, None)


# Backward-compatible name for callers/tests while the backend is replaceable.
AnalysisJobRegistry = InMemoryAnalysisJobBackend

jobs: AnalysisJobBackend = InMemoryAnalysisJobBackend()
