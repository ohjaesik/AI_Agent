"""Bounded in-memory analysis jobs used by the MCP interface.

The graph itself remains the source of truth. This registry only prevents a long
running MCP request from holding an HTTP connection and is intentionally replaceable
with a durable queue in production.
"""

from __future__ import annotations

import threading
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable, Protocol
from uuid import uuid4

from app.core.config import get_settings
from app.db.database import SessionLocal, engine
from app.db.models import MCPAnalysisJob
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


class DatabaseAnalysisJobBackend:
    """Database-backed job metadata with a process-local worker pool.

    The database makes status/results survive web process restarts. A queued
    callable cannot be serialized, so a separate worker/queue is still needed
    to resume jobs that were running when a process stopped.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._max_jobs = max(1, settings.mcp_max_jobs)
        self._ttl_seconds = max(60, settings.mcp_job_ttl_seconds)
        self._executor = ThreadPoolExecutor(max_workers=min(4, self._max_jobs), thread_name_prefix="mcp-analysis")
        MCPAnalysisJob.__table__.create(bind=engine, checkfirst=True)
        self._lock = threading.RLock()

    def submit(self, runner: Callable[[], dict[str, Any]]) -> str:
        with self._lock, SessionLocal() as db:
            self._prune(db)
            active = db.query(MCPAnalysisJob).filter(
                MCPAnalysisJob.status.in_(("queued", "running"))
            ).count()
            if active >= self._max_jobs:
                raise RuntimeError("MCP analysis job capacity is full.")
            analysis_id = f"analysis-{uuid4()}"
            now = _now()
            db.add(MCPAnalysisJob(
                analysis_id=analysis_id,
                status="queued",
                created_at=now,
                updated_at=now,
            ))
            db.commit()
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
        with SessionLocal() as db:
            job = db.get(MCPAnalysisJob, analysis_id)
            if not job:
                return
            job.status = changes.get("status", job.status)
            job.updated_at = _now()
            if "result" in changes:
                job.result_json = json.dumps(changes["result"], ensure_ascii=False, default=str)
            if "error" in changes:
                job.error = changes["error"]
            db.commit()

    def get(self, analysis_id: str) -> JobSnapshot | None:
        with self._lock, SessionLocal() as db:
            self._prune(db)
            job = db.get(MCPAnalysisJob, analysis_id)
            if not job:
                return None
            return {
                "analysis_id": job.analysis_id,
                "status": job.status,
                "created_at": job.created_at,
                "updated_at": job.updated_at,
                "result": json.loads(job.result_json) if job.result_json else None,
                "error": job.error,
            }

    def _prune(self, db: Any) -> None:
        now = datetime.now(timezone.utc).timestamp()
        jobs_to_remove = db.query(MCPAnalysisJob).filter(
            MCPAnalysisJob.status.notin_(("queued", "running"))
        ).all()
        for job in jobs_to_remove:
            if now - datetime.fromisoformat(job.updated_at).timestamp() > self._ttl_seconds:
                db.delete(job)
        db.flush()


# Backward-compatible name for callers/tests while the backend is replaceable.
AnalysisJobRegistry = InMemoryAnalysisJobBackend

def build_job_backend() -> AnalysisJobBackend:
    """Select the configured backend without changing adapter call sites."""
    backend = get_settings().mcp_job_backend.strip().lower()
    if backend == "database":
        return DatabaseAnalysisJobBackend()
    if backend != "memory":
        raise ValueError(f"Unsupported MCP_JOB_BACKEND: {backend}")
    return InMemoryAnalysisJobBackend()


jobs: AnalysisJobBackend = build_job_backend()
