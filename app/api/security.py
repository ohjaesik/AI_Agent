# app/api/security.py

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status

from app.core.config import get_settings
from app.security.access_control import AccessContext, DEFAULT_ROLE, ROLE_MAX_LEVEL


def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_user_role: str | None = Header(default=None, alias="X-User-Role"),
) -> AccessContext:
    """Protect API endpoints when APP_API_KEY is configured.

    Local/dev mode remains open if APP_API_KEY is not set. Production deployments
    should set APP_API_KEY and send it through the X-API-Key header.
    """
    expected = get_settings().app_api_key
    if expected and (not x_api_key or not secrets.compare_digest(x_api_key, expected)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
        )

    role = x_user_role if x_user_role in ROLE_MAX_LEVEL else DEFAULT_ROLE
    return AccessContext(user_id=x_user_id or "api-user", role=role)
