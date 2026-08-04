"""Tests for opsora_v2.is_provider_available — env-driven availability.

Contract (fix landing concurrently — red is expected until then):
- nvidia / alibaba have a health probe: key configured + probe healthy ⇒ True.
- alibaba's client getter accepts EITHER DASHSCOPE_API_KEY or OPENAI_API_KEY.
- openai / tokenhub / model_studio / opsora_api have NO health probe:
  availability is decided purely by configuration, and
  _check_provider_health must not be called for them.
- opsora_api needs BOTH OPSORA_API_URL and OPSORA_API_TOKEN.
- Nothing configured ⇒ nothing available.

The real environment loads keys at import time, so every test deletes all
provider env vars first (autouse fixture) and reset_globals() clears the
60-second health cache plus lazily-created clients.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "opsora_cmd"))

import opsora_v2


_PROVIDER_ENV_VARS = (
    "NVIDIA_API_KEY",
    "DASHSCOPE_API_KEY",
    "OPENAI_API_KEY",
    "TOKENHUB_API_KEY",
    "OPSORA_API_URL",
    "OPSORA_API_TOKEN",
    "AWS_PROFILE",
)


@pytest.fixture(autouse=True)
def _clean_provider_env(monkeypatch):
    """Reset module state and strip every provider credential."""
    opsora_v2.reset_globals()  # clears health cache + lazy clients + todos
    for var in _PROVIDER_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    yield


# ---------------------------------------------------------------------------
# Providers WITH a health probe (nvidia, alibaba)
# ---------------------------------------------------------------------------

class TestHealthProbedProviders:
    def test_nvidia_available_with_key_and_health(self, monkeypatch):
        monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-key")
        with patch("opsora_v2._check_provider_health", return_value=True) as mock_health:
            assert opsora_v2.is_provider_available("nvidia") is True
        mock_health.assert_called_once()

    def test_alibaba_available_with_dashscope_key(self, monkeypatch):
        monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-dashscope-test")
        with patch("opsora_v2._check_provider_health", return_value=True) as mock_health:
            assert opsora_v2.is_provider_available("alibaba") is True
        mock_health.assert_called_once()

    def test_alibaba_available_with_openai_key_only(self, monkeypatch):
        """get_alibaba_client accepts either key, so availability must too."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
        with patch("opsora_v2._check_provider_health", return_value=True) as mock_health:
            assert opsora_v2.is_provider_available("alibaba") is True
        mock_health.assert_called_once()


# ---------------------------------------------------------------------------
# Providers WITHOUT a health probe — configuration alone decides
# ---------------------------------------------------------------------------

class TestConfigOnlyProviders:
    def test_openai_available_and_no_health_check(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
        # Probe patched to False: if it were (wrongly) consulted, availability
        # would flip — the assert_not_called below is the real contract.
        with patch("opsora_v2._check_provider_health", return_value=False) as mock_health:
            assert opsora_v2.is_provider_available("openai") is True
        mock_health.assert_not_called()

    def test_tokenhub_available_and_no_health_check(self, monkeypatch):
        monkeypatch.setenv("TOKENHUB_API_KEY", "tokenhub-test-key")
        with patch("opsora_v2._check_provider_health", return_value=False) as mock_health:
            assert opsora_v2.is_provider_available("tokenhub") is True
        mock_health.assert_not_called()

    def test_model_studio_available_and_no_health_check(self, monkeypatch):
        monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-dashscope-test")
        with patch("opsora_v2._check_provider_health", return_value=False) as mock_health:
            assert opsora_v2.is_provider_available("model_studio") is True
        mock_health.assert_not_called()


# ---------------------------------------------------------------------------
# opsora_api — requires BOTH url and token, no health probe
# ---------------------------------------------------------------------------

class TestOpsoraApi:
    def test_url_and_token_available(self, monkeypatch):
        monkeypatch.setenv("OPSORA_API_URL", "https://api.opsora.example.com")
        monkeypatch.setenv("OPSORA_API_TOKEN", "opsora-test-token")
        with patch("opsora_v2._check_provider_health", return_value=False) as mock_health:
            assert opsora_v2.is_provider_available("opsora_api") is True
        mock_health.assert_not_called()

    def test_url_only_not_available(self, monkeypatch):
        monkeypatch.setenv("OPSORA_API_URL", "https://api.opsora.example.com")
        with patch("opsora_v2._check_provider_health", return_value=True) as mock_health:
            assert opsora_v2.is_provider_available("opsora_api") is False
        mock_health.assert_not_called()

    def test_token_only_not_available(self, monkeypatch):
        monkeypatch.setenv("OPSORA_API_TOKEN", "opsora-test-token")
        with patch("opsora_v2._check_provider_health", return_value=True) as mock_health:
            assert opsora_v2.is_provider_available("opsora_api") is False
        mock_health.assert_not_called()


# ---------------------------------------------------------------------------
# Nothing configured
# ---------------------------------------------------------------------------

class TestNothingConfigured:
    def test_all_providers_unavailable(self):
        # Health probe patched True so any (wrong) probe call would flip a
        # result — missing config must short-circuit before any probe.
        # bedrock is intentionally skipped (ambient AWS credentials may exist).
        with patch("opsora_v2._check_provider_health", return_value=True) as mock_health:
            for provider in ("nvidia", "alibaba", "model_studio",
                             "openai", "tokenhub", "opsora_api"):
                assert opsora_v2.is_provider_available(provider) is False, provider
        mock_health.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
