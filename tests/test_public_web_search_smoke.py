from app.ops.public_web_search_smoke import run_smoke, validate_provider_config


class DisabledSettings:
    external_web_discovery_enabled = False
    external_web_search_provider = "brave"
    brave_search_api_key = None
    serpapi_api_key = None
    external_web_max_results = 3


class BraveMissingKeySettings:
    external_web_discovery_enabled = True
    external_web_search_provider = "brave"
    brave_search_api_key = None
    serpapi_api_key = None
    external_web_max_results = 3


def test_public_web_search_smoke_requires_enabled(monkeypatch):
    monkeypatch.setattr("app.ops.public_web_search_smoke.get_settings", lambda: DisabledSettings())
    errors = validate_provider_config()
    assert any("EXTERNAL_WEB_DISCOVERY_ENABLED" in item for item in errors)


def test_public_web_search_smoke_requires_provider_key(monkeypatch):
    monkeypatch.setattr("app.ops.public_web_search_smoke.get_settings", lambda: BraveMissingKeySettings())
    result = run_smoke("Samsung Electronics", ["governance"], 3)
    assert result["ok"] is False
    assert result["stage"] == "config"
