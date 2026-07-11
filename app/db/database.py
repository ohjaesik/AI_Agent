# app/db/database.py

"""SQLAlchemy engine/session factory 설정.

.env의 DATABASE_URL을 기준으로 DB 연결을 만들고, 각 node/API가 사용할 SessionLocal을
제공한다.
"""

from collections.abc import Generator

from pgvector.psycopg import register_vector
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


settings = get_settings()


class Base(DeclarativeBase):
    """SQLAlchemy declarative model들이 상속하는 공통 base class다."""
    pass


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    future=True,
)


@event.listens_for(engine, "connect")
def register_pgvector(dbapi_connection, connection_record):
    """
    psycopg3 connection에 pgvector type을 등록한다.
    """
    register_vector(dbapi_connection)


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    class_=Session,
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency에서 사용할 DB session generator다."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()