"""Uvicorn 기본 실행 경로를 위한 FastAPI app re-export.

프로젝트의 실제 API 앱은 `app/api/main.py`에 있다. 다만 로컬에서 습관적으로
`uvicorn main:app ...`을 실행해도 같은 FastAPI 앱이 뜨도록 루트 진입점을 둔다.
"""

from app.api.main import app

__all__ = ["app"]
