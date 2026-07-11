# app/db/init_pgvector.py

"""PostgreSQL pgvector extension 초기화 script.

RAG embedding column과 vector distance 검색을 사용하기 위해 필요한 DB extension을
준비한다.
"""

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.database import engine


def main() -> None:
    """해당 모듈을 script로 실행했을 때 호출되는 진입점이다."""
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))

            result = conn.execute(
                text(
                    """
                    SELECT extname
                    FROM pg_extension
                    WHERE extname = 'vector';
                    """
                )
            ).scalar_one_or_none()

            if result == "vector":
                print("pgvector extension is ready.")
            else:
                raise RuntimeError("pgvector extension was not found after creation attempt.")

    except SQLAlchemyError as exc:
        print("Failed to initialize pgvector extension.")
        print("Ask DB admin to run: CREATE EXTENSION IF NOT EXISTS vector;")
        raise exc


if __name__ == "__main__":
    main()