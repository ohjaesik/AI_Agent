import pytest
from fastapi import HTTPException

from app.api.security import require_api_key


class DummySettings:
    app_api_key = None


def test_api_key_guard_is_open_when_not_configured(monkeypatch):
    monkeypatch.setattr("app.api.security.get_settings", lambda: DummySettings())
    assert require_api_key(None) is None


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
    assert require_api_key("secret") is None
