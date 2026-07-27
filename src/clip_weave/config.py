"""clip-weave configuration — loads from env vars and optional config.yaml."""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


@dataclass
class Config:
    gemini_api_key: str = ""
    openai_api_key: str = ""
    heygen_api_key: str = ""
    figma_token: str = ""

    embedding_provider: str = "gemini"   # gemini | openai | local
    vision_provider: str = "gemini"      # gemini | openai
    tts_provider: str = "heygen"         # heygen | kokoro

    @property
    def has_embedding(self) -> bool:
        if self.embedding_provider == "gemini":
            return bool(self.gemini_api_key)
        if self.embedding_provider == "openai":
            return bool(self.openai_api_key)
        return False


def _load_yaml_providers(config_path: Path) -> dict:
    if not config_path.exists():
        return {}
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(config_path.read_text()) or {}
        return data.get("providers", {})
    except Exception as exc:
        logger.debug("Could not load config.yaml: %s", exc)
        return {}


def load_config(project_root: Path | None = None) -> Config:
    root = project_root or Path.cwd()
    providers = _load_yaml_providers(root / "config.yaml")

    gemini_key = os.getenv("GEMINI_API_KEY", os.getenv("GOOGLE_API_KEY", ""))
    openai_key = os.getenv("OPENAI_API_KEY", "")

    if not gemini_key and not openai_key:
        logger.warning(
            "No embedding API key found. Asset Matcher will use keyword matching. "
            "Set GEMINI_API_KEY in .env or environment."
        )

    return Config(
        gemini_api_key=gemini_key,
        openai_api_key=openai_key,
        heygen_api_key=os.getenv("HEYGEN_API_KEY", ""),
        figma_token=os.getenv("FIGMA_TOKEN", ""),
        embedding_provider=providers.get("embedding", "gemini"),
        vision_provider=providers.get("vision", "gemini"),
        tts_provider=providers.get("tts", "heygen"),
    )
