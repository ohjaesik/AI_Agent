# app/db/migrate_discovery_metadata.py

"""업무 discovery metadata 관련 DB migration script.

기존 DB에 후보 업무 source label, discovery metadata 같은 컬럼/구조를 추가하는 데
사용한다.
"""

from __future__ import annotations

from sqlalchemy import text

from app.db.database import engine


def ensure_discovery_metadata_column() -> None:
    """ensure_discovery_metadata_column 함수. 업무 discovery metadata 관련 DB migration script. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
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
    """해당 모듈을 script로 실행했을 때 호출되는 진입점이다."""
    ensure_discovery_metadata_column()
    print("business_processes.discovery_metadata is ready.")


if __name__ == "__main__":
    main()
