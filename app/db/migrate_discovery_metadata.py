# app/db/migrate_discovery_metadata.py

from __future__ import annotations

from sqlalchemy import text

from app.db.database import engine


def ensure_discovery_metadata_column() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                ALTER TABLE IF EXISTS business_processes
                ADD COLUMN IF NOT EXISTS discovery_metadata JSONB;
                """
            )
        )


def main() -> None:
    ensure_discovery_metadata_column()
    print("business_processes.discovery_metadata is ready.")


if __name__ == "__main__":
    main()
