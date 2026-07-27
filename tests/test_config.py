import os
from pathlib import Path
from unittest.mock import patch
import pytest
from clip_weave.config import load_config


def test_load_config_defaults():
    with patch.dict(os.environ, {}, clear=True):
        cfg = load_config()
    assert cfg.embedding_provider == "gemini"
    assert cfg.vision_provider == "gemini"
    assert cfg.tts_provider == "heygen"
    assert cfg.gemini_api_key == ""
    assert cfg.openai_api_key == ""


def test_load_config_gemini_key():
    with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True):
        cfg = load_config()
    assert cfg.gemini_api_key == "test-key"
    assert cfg.has_embedding is True


def test_load_config_google_api_key_fallback():
    with patch.dict(os.environ, {"GOOGLE_API_KEY": "goog-key"}, clear=True):
        cfg = load_config()
    assert cfg.gemini_api_key == "goog-key"


def test_load_config_openai_key():
    with patch.dict(os.environ, {"OPENAI_API_KEY": "oai-key"}, clear=True):
        cfg = load_config()
    assert cfg.openai_api_key == "oai-key"


def test_has_embedding_false_without_keys():
    with patch.dict(os.environ, {}, clear=True):
        cfg = load_config()
    assert cfg.has_embedding is False


def test_has_embedding_true_with_gemini():
    with patch.dict(os.environ, {"GEMINI_API_KEY": "k"}, clear=True):
        cfg = load_config()
    assert cfg.has_embedding is True


def test_load_config_warns_without_keys(caplog):
    import logging
    with patch.dict(os.environ, {}, clear=True):
        with caplog.at_level(logging.WARNING, logger="clip_weave.config"):
            load_config()
    assert "GEMINI_API_KEY" in caplog.text


def test_load_config_yaml_providers(tmp_path):
    config_yaml = tmp_path / "config.yaml"
    config_yaml.write_text("providers:\n  embedding: openai\n  tts: kokoro\n")
    with patch.dict(os.environ, {"OPENAI_API_KEY": "oai-key"}, clear=True):
        cfg = load_config(project_root=tmp_path)
    assert cfg.embedding_provider == "openai"
    assert cfg.tts_provider == "kokoro"
