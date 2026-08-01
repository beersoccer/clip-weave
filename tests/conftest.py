"""Shared pytest fixtures."""

import pytest

_GATEWAY_VARS = (
    "ROUTER_BASE_URL",
    "ROUTER_API_KEY",
    "ROUTER_MODEL",
    "VIDEO_ANALYSIS_BASE_URL",
    "VIDEO_ANALYSIS_API_KEY",
    "VIDEO_ANALYSIS_MODEL",
    "HTML_GEN_BASE_URL",
    "HTML_GEN_API_KEY",
    "HTML_GEN_MODEL",
    "EMBEDDING_BASE_URL",
    "EMBEDDING_API_KEY",
)


@pytest.fixture(autouse=True)
def offline_by_default(monkeypatch):
    """Keep the suite offline.

    `clip_weave.config` calls `load_dotenv()` at import, so a developer's real `.env`
    would otherwise make semantic routing and asset matching hit the live gateway.
    Tests that want a gateway set the variables back themselves.
    """
    for var in _GATEWAY_VARS:
        monkeypatch.delenv(var, raising=False)
