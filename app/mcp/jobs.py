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

from sqlalchemy import inspect, text

from app.core.config import get_settings
from app.db.database import SessionLocal, engine
from app.db.models import MCPAnalysisJob
from app.mcp.schemas import JobSnapshot, JobStatus


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AnalysisJobBackend(Protocol):
    """Durable storage/queue contract used by the MCP adapter."""

    def submit(self, runner: Callable[[], dict[str, Any]], *, owner_user_id: str = "mcp-user",
               company_id: int | None = None, project_id: int | None = None) -> str: ...
    def get(self, analysis_id: str) -> JobSnapshot | None: ...
    def retry(self, analysis_id: str, runner: Callable[[], dict[str, Any]]) -> None: ...


class InMemoryAnalysisJobBackend:
    def __init__(self) -> None:
        settings = get_settings()
        self._max_jobs = max(1, settings.mcp_max_jobs)
        self._ttl_seconds = max(60, settings.mcp_job_ttl_seconds)
        self._executor = ThreadPoolExecutor(max_workers=min(4, self._max_jobs), thread_name_prefix="mcp-analysis")
        self._jobs: dict[str, JobSnapshot] = {}
        self._lock = threading.RLock()

    def submit(self, runner: Callable[[], dict[str, Any]], *, owner_user_id: str = "mcp-user",
               company_id: int | None = None, project_id: int | None = None) -> str:
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
                "owner_user_id": owner_user_id,
                "company_id": company_id,
                "project_id": project_id,
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

    def retry(self, analysis_id: str, runner: Callable[[], dict[str, Any]]) -> None:
        with self._lock:
            snapshot = self._jobs.get(analysis_id)
            if not snapshot or snapshot["status"] != "recoverable":
                raise ValueError("Only recoverable MCP jobs can be retried.")
            snapshot["status"] = "queued"
            snapshot["error"] = None
            snapshot["updated_at"] = _now()
        self._executor.submit(self._run, analysis_id, runner)

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
        self._ensure_owner_columns()
        self._recover_stale_jobs()
        self._lock = threading.RLock()

    def _ensure_owner_columns(self) -> None:
        """Upgrade the small standalone table for installations without migrations yet."""
        columns = {item["name"] for item in inspect(engine).get_columns("mcp_analysis_jobs")}
        additions = {
            "owner_user_id": "VARCHAR(100) NOT NULL DEFAULT 'mcp-user'",
            "company_id": "INTEGER",
            "project_id": "INTEGER",
            "job_type": "VARCHAR(80) NOT NULL DEFAULT 'delivery_analysis'",
        }
        with engine.begin() as connection:
            for name, definition in additions.items():
                if name not in columns:
                    connection.execute(text(f"ALTER TABLE mcp_analysis_jobs ADD COLUMN {name} {definition}"))

    def _recover_stale_jobs(self) -> None:
        """Make interrupted work explicit instead of falsely leaving it running."""
        with SessionLocal() as db:
            db.query(MCPAnalysisJob).filter(MCPAnalysisJob.status == "running").update(
                {"status": "recoverable", "error": "Worker stopped before completion."},
                synchronize_session=False,
            )
            db.commit()

    def submit(self, runner: Callable[[], dict[str, Any]], *, owner_user_id: str = "mcp-user",
               company_id: int | None = None, project_id: int | None = None) -> str:
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
                owner_user_id=owner_user_id,
                company_id=company_id,
                project_id=project_id,
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
                "owner_user_id": job.owner_user_id,
                "company_id": job.company_id,
                "project_id": job.project_id,
            }

    def retry(self, analysis_id: str, runner: Callable[[], dict[str, Any]]) -> None:
        with self._lock, SessionLocal() as db:
            job = db.get(MCPAnalysisJob, analysis_id)
            if not job or job.status != "recoverable":
                raise ValueError("Only recoverable MCP jobs can be retried.")
            job.status = "queued"
            job.error = None
            job.updated_at = _now()
            db.commit()
        self._executor.submit(self._run, analysis_id, runner)

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
