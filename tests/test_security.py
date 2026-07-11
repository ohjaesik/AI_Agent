"""API key/JWT/role 기반 접근 제어를 검증한다.
"""

import pytest
from fastapi import HTTPException

from app.api.security import create_access_token, require_api_key
from app.security.access_control import allowed_security_levels

TEST_JWT_SECRET = "test-jwt-secret-at-least-32-bytes-long"


class DummySettings:
    app_api_key = None
    app_jwt_secret = None
    app_jwt_algorithm = "HS256"
    app_jwt_exp_minutes = 480


def test_api_key_guard_is_open_when_not_configured(monkeypatch):
    monkeypatch.setattr("app.api.security.get_settings", lambda: DummySettings())
    context = require_api_key(None)
    assert context.role == "analyst"


def test_api_key_guard_rejects_missing_key(monkeypatch):
    class Settings:
        app_api_key = "secret"
        app_jwt_secret = None
        app_jwt_algorithm = "HS256"
        app_jwt_exp_minutes = 480

    monkeypatch.setattr("app.api.security.get_settings", lambda: Settings())

    with pytest.raises(HTTPException) as exc:
        require_api_key(None)

    assert exc.value.status_code == 401


def test_api_key_guard_accepts_matching_key(monkeypatch):
    class Settings:
        app_api_key = "secret"
        app_jwt_secret = None
        app_jwt_algorithm = "HS256"
        app_jwt_exp_minutes = 480

    monkeypatch.setattr("app.api.security.get_settings", lambda: Settings())
    context = require_api_key("secret", x_user_role="admin")
    assert context.role == "admin"


def test_jwt_auth_accepts_bearer_token(monkeypatch):
    class Settings:
        app_api_key = "secret"
        app_jwt_secret = TEST_JWT_SECRET
        app_jwt_algorithm = "HS256"
        app_jwt_exp_minutes = 480

    monkeypatch.setattr("app.api.security.get_settings", lambda: Settings())
    token = create_access_token("user-1", "manager")
    context = require_api_key(authorization=f"Bearer {token}")

    assert context.user_id == "user-1"
    assert context.role == "manager"


def test_role_based_security_levels():
    assert "confidential" not in allowed_security_levels("analyst")
    assert "confidential" in allowed_security_levels("manager")
    assert "restricted" in allowed_security_levels("admin")
