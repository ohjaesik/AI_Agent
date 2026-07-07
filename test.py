# app/db/check_pgvector.py

from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os

load_dotenv()

engine = create_engine(os.getenv("DATABASE_URL"), pool_pre_ping=True)

with engine.connect() as conn:
    result = conn.execute(text("""
        SELECT extname
        FROM pg_extension
        WHERE extname = 'vector';
    """))
    extension = result.scalar()

    if extension == "vector":
        print("pgvector extension is installed.")
    else:
        print("pgvector extension is NOT installed.")