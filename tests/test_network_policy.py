import pytest

from app.agents.network_policy import assert_network_target_allowed


def test_official_source_requires_https():
    with pytest.raises(PermissionError):
        assert_network_target_allowed("http://example.com/company", "official_sources_only")


def test_network_policy_rejects_private_targets():
    with pytest.raises(PermissionError):
        assert_network_target_allowed("https://127.0.0.1/internal", "official_sources_only")


def test_network_policy_rejects_embedded_credentials():
    with pytest.raises(ValueError):
        assert_network_target_allowed("https://user:pass@example.com", "official_sources_only")
