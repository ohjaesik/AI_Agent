# app/db/create_tables.py

from app.db.database import Base, engine

# 중요: 모델 import가 있어야 Base.metadata에 테이블들이 등록됨
from app.db import models  # noqa: F401


def main() -> None:
    Base.metadata.create_all(bind=engine)
    print("Tables created successfully.")


if __name__ == "__main__":
    main()