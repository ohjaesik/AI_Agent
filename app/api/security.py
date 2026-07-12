# app/api/security.py

"""API key와 JWT 기반 접근 제어 helper.

로컬/데모 API에서 X-API-Key, Bearer token을 검증하고 요청자의 user_id/role을
AccessContext로 변환한다.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

import jwt
from fastapi import Header, HTTPException, status

from app.core.config import get_settings
from app.security.access_control import AccessContext, DEFAULT_ROLE, ROLE_MAX_LEVEL


def normalize_role(role: str | None) -> str:
    """알 수 없는 role은 기본 analyst 권한으로 낮춘다."""
    return role if role in ROLE_MAX_LEVEL else DEFAULT_ROLE


def create_access_token(user_id: str, role: str, expires_minutes: int | None = None) -> str:
    """로컬 로그인/API 테스트용 JWT access token을 생성한다."""
    settings = get_settings()
    if not settings.app_jwt_secret:
        raise HTTPException(status_code=400, detail="APP_JWT_SECRET is not configured.")

    expires_delta = timedelta(minutes=expires_minutes or settings.app_jwt_exp_minutes)
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": user_id,
        "role": normalize_role(role),
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    return jwt.encode(payload, settings.app_jwt_secret, algorithm=settings.app_jwt_algorithm)


def decode_access_token(token: str) -> AccessContext:
    """Bearer JWT를 검증하고 요청자 정보를 AccessContext로 변환한다."""
    settings = get_settings()
    if not settings.app_jwt_secret:
        raise HTTPException(status_code=401, detail="JWT authentication is not configured.")

    try:
        payload = jwt.decode(token, settings.app_jwt_secret, algorithms=[settings.app_jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="JWT token expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Invalid JWT token.") from exc

    return AccessContext(
        user_id=str(payload.get("sub") or "jwt-user"),
        role=normalize_role(str(payload.get("role") or DEFAULT_ROLE)),
    )


def validate_api_key(x_api_key: str | None) -> None:
    """APP_API_KEY가 설정된 환경에서 X-API-Key header를 검증한다."""
    expected = get_settings().app_api_key
    if expected and (not x_api_key or not secrets.compare_digest(x_api_key, expected)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
        )


def require_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
    x_user_role: Annotated[str | None, Header(alias="X-User-Role")] = None,
) -> AccessContext:
    """API endpoint 공통 인증 dependency.

    우선순위:
    1. Authorization Bearer JWT가 있으면 JWT를 검증한다.
    2. 없으면 X-API-Key와 X-User-* header를 검증/해석한다.
    3. APP_API_KEY와 APP_JWT_SECRET이 모두 비어 있는 로컬 개발 환경만 열린 모드로 둔다.
    """
    settings = get_settings()

    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        return decode_access_token(token)

    validate_api_key(x_api_key)

    if not settings.app_api_key and settings.app_jwt_secret:
        raise HTTPException(status_code=401, detail="Bearer token required.")

    role = normalize_role(x_user_role)
    return AccessContext(user_id=x_user_id or "api-user", role=role)
