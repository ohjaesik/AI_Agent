"""Idempotent migration for durable MCP analysis jobs."""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.db.database import engine
from app.db.models import MCPAnalysisJob


def migrate_mcp_jobs() -> None:
    """Create the MCP job table and add columns used by newer job contracts."""
    MCPAnalysisJob.__table__.create(bind=engine, checkfirst=True)
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


def main() -> None:
    migrate_mcp_jobs()
    print("MCP analysis job migration completed.")


if __name__ == "__main__":
    main()
