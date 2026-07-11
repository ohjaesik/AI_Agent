"""로컬 PostgreSQL에 pgvector extension이 설치되어 있는지 확인하는 보조 스크립트.

개발자가 RAG 색인이나 vector similarity 검색이 실패할 때 가장 먼저 확인할 수 있는
간단한 진단용 파일이다. 실제 애플리케이션 실행 경로에는 포함되지 않고, 터미널에서
직접 실행해 DB extension 상태만 빠르게 출력한다.
"""

from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os

# `.env`에 적힌 DATABASE_URL을 읽어 로컬/운영 DB 접속 정보를 재사용한다.
load_dotenv()

# pool_pre_ping=True는 오래된 연결을 재사용할 때 끊어진 DB connection을 먼저 확인한다.
engine = create_engine(os.getenv("DATABASE_URL"), pool_pre_ping=True)

with engine.connect() as conn:
    # PostgreSQL extension catalog에서 vector extension 등록 여부만 조회한다.
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
