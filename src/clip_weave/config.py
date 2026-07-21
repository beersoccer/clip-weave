import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


@dataclass
class Config:
    video_analysis_base_url: str | None  # None = SDK default (direct vendor)
    video_analysis_api_key: str
    video_analysis_model: str

    html_gen_base_url: str | None        # None = SDK default (direct vendor)
    html_gen_api_key: str
    html_gen_model: str

    pexels_api_key: str
    scene_threshold: float


def load_config() -> Config:
    video_analysis_api_key = os.getenv("VIDEO_ANALYSIS_API_KEY", "")
    html_gen_api_key = os.getenv("HTML_GEN_API_KEY", "")

    if not video_analysis_api_key:
        logger.warning(
            "VIDEO_ANALYSIS_API_KEY is not set — video analysis will fail. "
            "Add it to .env: VIDEO_ANALYSIS_API_KEY=<your_key>"
        )
    if not html_gen_api_key:
        logger.warning(
            "HTML_GEN_API_KEY is not set — HTML generation will fail. "
            "Add it to .env: HTML_GEN_API_KEY=<your_key>"
        )

    threshold_raw = os.getenv("SCENE_THRESHOLD", "0.35")
    try:
        threshold = float(threshold_raw)
    except ValueError:
        logger.warning(
            "SCENE_THRESHOLD='%s' is not a valid float, using default 0.35",
            threshold_raw,
        )
        threshold = 0.35

    video_analysis_base_url = os.getenv("VIDEO_ANALYSIS_BASE_URL") or None
    html_gen_base_url = os.getenv("HTML_GEN_BASE_URL") or None

    # OpenAI SDK appends /chat/completions to base_url directly; the gateway's
    # Vertex path requires /v1 to be present in base_url (e.g. …/vertex/v1).
    if video_analysis_base_url and not video_analysis_base_url.rstrip("/").endswith("v1"):
        logger.warning(
            "VIDEO_ANALYSIS_BASE_URL='%s' does not end with /v1. "
            "OpenAI SDK will call %s/chat/completions — ensure this matches your gateway. "
            "Typical correct value: %s/v1",
            video_analysis_base_url,
            video_analysis_base_url.rstrip("/"),
            video_analysis_base_url.rstrip("/"),
        )

    # Claude model names differ between gateway (global.anthropic.*) and direct API.
    # Auto-select the right default so users only need to set BASE_URL.
    default_html_model = (
        "global.anthropic.claude-sonnet-4-6" if html_gen_base_url else "claude-sonnet-4-6"
    )

    return Config(
        video_analysis_base_url=video_analysis_base_url,
        video_analysis_api_key=video_analysis_api_key,
        video_analysis_model=os.getenv("VIDEO_ANALYSIS_MODEL", "gemini-2.5-flash"),
        html_gen_base_url=html_gen_base_url,
        html_gen_api_key=html_gen_api_key,
        html_gen_model=os.getenv("HTML_GEN_MODEL", default_html_model),
        pexels_api_key=os.getenv("PEXELS_API_KEY", ""),
        scene_threshold=threshold,
    )
