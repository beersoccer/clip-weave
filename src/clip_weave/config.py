"""clip-weave configuration — loads from env vars."""

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


@dataclass
class Config:
    gemini_api_key: str = ""
    openai_api_key: str = ""
    figma_token: str = ""

    # Vision gateway — Asset Matcher image description enrichment (chat/completions).
    video_analysis_base_url: str = ""
    video_analysis_api_key: str = ""
    video_analysis_model: str = "gemini-2.5-flash"

    # Embedding gateway — semantic ranking (/v1/embeddings, OpenAI-compatible).
    # Independent of video_analysis_*; falls back to BM25 when not configured.
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"

    @property
    def has_vision(self) -> bool:
        return bool(self.video_analysis_api_key or self.gemini_api_key or self.openai_api_key)

    @property
    def has_embedding(self) -> bool:
        return bool(self.embedding_base_url and self.embedding_api_key)


def load_config(project_root: Path | None = None) -> Config:
    root = project_root or Path.cwd()
    _ = root  # reserved for future project-local config.yaml support

    gemini_key = os.getenv("GEMINI_API_KEY", os.getenv("GOOGLE_API_KEY", ""))
    openai_key = os.getenv("OPENAI_API_KEY", "")
    va_key = os.getenv("VIDEO_ANALYSIS_API_KEY", "")
    embed_key = os.getenv("EMBEDDING_API_KEY", "")

    if not gemini_key and not openai_key and not va_key and not embed_key:
        logger.warning(
            "No vision/embedding API key found. Asset Matcher will use keyword matching. "
            "Set VIDEO_ANALYSIS_API_KEY (vision) or EMBEDDING_API_KEY (embeddings) in .env."
        )

    return Config(
        gemini_api_key=gemini_key,
        openai_api_key=openai_key,
        figma_token=os.getenv("FIGMA_TOKEN", ""),
        video_analysis_base_url=os.getenv("VIDEO_ANALYSIS_BASE_URL", ""),
        video_analysis_api_key=va_key,
        video_analysis_model=os.getenv("VIDEO_ANALYSIS_MODEL", "gemini-2.5-flash"),
        embedding_base_url=os.getenv("EMBEDDING_BASE_URL", ""),
        embedding_api_key=embed_key,
        embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
    )
