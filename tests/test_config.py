import os
from unittest.mock import patch

import pytest

from clip_weave.config import load_config


def _env(**kwargs) -> dict:
    base = {
        "VIDEO_ANALYSIS_API_KEY": "va-key",
        "HTML_GEN_API_KEY": "hg-key",
    }
    base.update(kwargs)
    return base


def test_load_config_defaults():
    with patch.dict(os.environ, _env(), clear=True):
        cfg = load_config()
    assert cfg.video_analysis_model == "gemini-2.0-flash-exp"
    assert cfg.html_gen_model == "claude-sonnet-4-6"
    assert cfg.scene_threshold == 0.35
    assert cfg.video_analysis_base_url is None
    assert cfg.html_gen_base_url is None


def test_load_config_custom_values():
    with patch.dict(os.environ, _env(
        VIDEO_ANALYSIS_BASE_URL="http://gw.example.com/v1",
        VIDEO_ANALYSIS_MODEL="gpt-4o",
        HTML_GEN_BASE_URL="http://gw.example.com/v1",
        HTML_GEN_MODEL="claude-opus-4-7",
        SCENE_THRESHOLD="0.5",
    ), clear=True):
        cfg = load_config()
    assert cfg.video_analysis_base_url == "http://gw.example.com/v1"
    assert cfg.video_analysis_model == "gpt-4o"
    assert cfg.html_gen_base_url == "http://gw.example.com/v1"
    assert cfg.html_gen_model == "claude-opus-4-7"
    assert cfg.scene_threshold == 0.5


def test_load_config_empty_base_url_becomes_none():
    with patch.dict(os.environ, _env(
        VIDEO_ANALYSIS_BASE_URL="",
        HTML_GEN_BASE_URL="",
    ), clear=True):
        cfg = load_config()
    assert cfg.video_analysis_base_url is None
    assert cfg.html_gen_base_url is None


def test_load_config_invalid_threshold_warns_and_defaults(caplog):
    import logging
    with patch.dict(os.environ, _env(SCENE_THRESHOLD="not-a-float"), clear=True):
        with caplog.at_level(logging.WARNING, logger="clip_weave.config"):
            cfg = load_config()
    assert cfg.scene_threshold == 0.35
    assert "SCENE_THRESHOLD" in caplog.text


def test_load_config_missing_api_keys_warns(caplog):
    import logging
    with patch.dict(os.environ, {}, clear=True):
        with caplog.at_level(logging.WARNING, logger="clip_weave.config"):
            cfg = load_config()
    assert cfg.video_analysis_api_key == ""
    assert cfg.html_gen_api_key == ""
    assert "VIDEO_ANALYSIS_API_KEY" in caplog.text
    assert "HTML_GEN_API_KEY" in caplog.text


def test_load_config_any_model_string_accepted():
    """Model names are free-form strings; no validation errors should be raised."""
    with patch.dict(os.environ, _env(HTML_GEN_MODEL="any-model-name-v99"), clear=True):
        cfg = load_config()
    assert cfg.html_gen_model == "any-model-name-v99"
