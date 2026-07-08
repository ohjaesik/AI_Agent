# app/api/security.py

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status

from app.core.config import get_settings


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    """Protect API endpoints when APP_API_KEY is configured.

    Local/dev mode remains open if APP_API_KEY is not set. Production deployments
    should set APP_API_KEY and send it through the X-API-Key header.
    """
    expected = get_settings().app_api_key
    if not expected:
        return

    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
        )
