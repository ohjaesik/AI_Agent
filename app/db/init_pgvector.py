# app/db/init_pgvector.py

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.database import engine


def main() -> None:
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