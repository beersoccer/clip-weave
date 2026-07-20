import os
import pytest
from unittest.mock import patch
from clip_weave.config import load_config


def test_load_config_defaults():
    env = {
        "ANTHROPIC_API_KEY": "test-ant",
        "OPENAI_API_KEY": "test-oai",
        "GEMINI_API_KEY": "test-gem",
        "PEXELS_API_KEY": "test-pex",
    }
    with patch.dict(os.environ, env, clear=False):
        cfg = load_config()
    assert cfg.html_gen_model == "claude"
    assert cfg.scene_threshold == 0.35


def test_load_config_custom_model():
    env = {
        "ANTHROPIC_API_KEY": "k", "OPENAI_API_KEY": "k",
        "GEMINI_API_KEY": "k", "PEXELS_API_KEY": "k",
        "HTML_GEN_MODEL": "gpt4o",
        "SCENE_THRESHOLD": "0.5",
    }
    with patch.dict(os.environ, env, clear=False):
        cfg = load_config()
    assert cfg.html_gen_model == "gpt4o"
    assert cfg.scene_threshold == 0.5


def test_load_config_invalid_model_raises():
    env = {
        "ANTHROPIC_API_KEY": "k", "OPENAI_API_KEY": "k",
        "GEMINI_API_KEY": "k", "PEXELS_API_KEY": "k",
        "HTML_GEN_MODEL": "unknown",
    }
    with patch.dict(os.environ, env, clear=False):
        with pytest.raises(ValueError, match="HTML_GEN_MODEL"):
            load_config()
