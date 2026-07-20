import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

VALID_HTML_MODELS = {"claude", "gpt4o"}


@dataclass
class Config:
    anthropic_api_key: str
    openai_api_key: str
    gemini_api_key: str
    pexels_api_key: str
    html_gen_model: str
    scene_threshold: float


def load_config() -> Config:
    model = os.getenv("HTML_GEN_MODEL", "claude")
    if model not in VALID_HTML_MODELS:
        raise ValueError(f"HTML_GEN_MODEL must be one of {VALID_HTML_MODELS}, got '{model}'")
    return Config(
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        pexels_api_key=os.getenv("PEXELS_API_KEY", ""),
        html_gen_model=model,
        scene_threshold=float(os.getenv("SCENE_THRESHOLD", "0.35")),
    )
