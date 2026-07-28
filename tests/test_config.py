import os
from unittest.mock import patch
import pytest
from clip_weave.config import load_config


def test_load_config_defaults():
    with patch.dict(os.environ, {}, clear=True):
        cfg = load_config()
    assert cfg.gemini_api_key == ""
    assert cfg.openai_api_key == ""
    assert cfg.video_analysis_api_key == ""
    assert cfg.video_analysis_model == "gemini-2.5-flash"


def test_load_config_gemini_key():
    with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True):
        cfg = load_config()
    assert cfg.gemini_api_key == "test-key"
    assert cfg.has_vision is True


def test_load_config_google_api_key_fallback():
    with patch.dict(os.environ, {"GOOGLE_API_KEY": "goog-key"}, clear=True):
        cfg = load_config()
    assert cfg.gemini_api_key == "goog-key"


def test_load_config_openai_key():
    with patch.dict(os.environ, {"OPENAI_API_KEY": "oai-key"}, clear=True):
        cfg = load_config()
    assert cfg.openai_api_key == "oai-key"


def test_load_config_video_analysis_gateway():
    env = {
        "VIDEO_ANALYSIS_API_KEY": "va-key",
        "VIDEO_ANALYSIS_BASE_URL": "https://gateway.example.com/v1/",
        "VIDEO_ANALYSIS_MODEL": "gemini-2.5-flash",
    }
    with patch.dict(os.environ, env, clear=True):
        cfg = load_config()
    assert cfg.video_analysis_api_key == "va-key"
    assert cfg.video_analysis_base_url == "https://gateway.example.com/v1/"
    assert cfg.video_analysis_model == "gemini-2.5-flash"
    assert cfg.has_vision is True


def test_load_config_embedding_gateway():
    env = {
        "EMBEDDING_BASE_URL": "http://gateway/gptembed/",
        "EMBEDDING_API_KEY": "embed-key",
        "EMBEDDING_MODEL": "text-embedding-3-small",
    }
    with patch.dict(os.environ, env, clear=True):
        cfg = load_config()
    assert cfg.embedding_base_url == "http://gateway/gptembed/"
    assert cfg.embedding_api_key == "embed-key"
    assert cfg.embedding_model == "text-embedding-3-small"
    assert cfg.has_embedding is True


def test_load_config_embedding_independent_from_vision():
    """EMBEDDING_* and VIDEO_ANALYSIS_* are independent; setting only vision does not enable embedding."""
    env = {"VIDEO_ANALYSIS_API_KEY": "va-key", "VIDEO_ANALYSIS_BASE_URL": "https://vision.example.com/v1/"}
    with patch.dict(os.environ, env, clear=True):
        cfg = load_config()
    assert cfg.has_vision is True
    assert cfg.has_embedding is False   # embedding needs its own EMBEDDING_* config


def test_load_config_warns_without_keys(caplog):
    import logging
    with patch.dict(os.environ, {}, clear=True):
        with caplog.at_level(logging.WARNING, logger="clip_weave.config"):
            load_config()
    assert "VIDEO_ANALYSIS_API_KEY" in caplog.text
