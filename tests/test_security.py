import pytest
from fastapi import HTTPException

from app.api.security import require_api_key
from app.security.access_control import allowed_security_levels


class DummySettings:
    app_api_key = None


def test_api_key_guard_is_open_when_not_configured(monkeypatch):
    monkeypatch.setattr("app.api.security.get_settings", lambda: DummySettings())
    context = require_api_key(None)
    assert context.role == "analyst"


def test_api_key_guard_rejects_missing_key(monkeypatch):
    class Settings:
        app_api_key = "secret"

    monkeypatch.setattr("app.api.security.get_settings", lambda: Settings())

    with pytest.raises(HTTPException) as exc:
        require_api_key(None)

    assert exc.value.status_code == 401


def test_api_key_guard_accepts_matching_key(monkeypatch):
    class Settings:
        app_api_key = "secret"

    monkeypatch.setattr("app.api.security.get_settings", lambda: Settings())
    context = require_api_key("secret", x_user_role="admin")
    assert context.role == "admin"


def test_role_based_security_levels():
    assert "confidential" not in allowed_security_levels("analyst")
    assert "confidential" in allowed_security_levels("manager")
    assert "restricted" in allowed_security_levels("admin")
