# app/db/create_tables.py

"""SQLAlchemy model 기준으로 DB table을 생성하는 script.

로컬 개발/초기 데모 환경에서 schema를 빠르게 준비할 때 사용한다.
"""

from app.db.database import Base, engine

# 중요: 모델 import가 있어야 Base.metadata에 테이블들이 등록됨
from app.db import models  # noqa: F401


def main() -> None:
    """해당 모듈을 script로 실행했을 때 호출되는 진입점이다."""
    Base.metadata.create_all(bind=engine)
    print("Tables created successfully.")


if __name__ == "__main__":
    main()