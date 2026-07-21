import logging
import re
from datetime import datetime
from pathlib import Path

from openai import OpenAI

from clip_weave.config import Config
from clip_weave.schemas.brand_assets import BrandAssets
from clip_weave.schemas.shots import ShotsOutput

logger = logging.getLogger(__name__)

_HTML_RE = re.compile(r"<html[\s>]", re.IGNORECASE)
_MAX_RETRIES = 2


def _build_prompt(shots: ShotsOutput, brand: BrandAssets) -> str:
    shots_desc = "\n".join(
        f"Shot {s.index} ({s.type}, {s.duration}s): {s.visual_element}"
        + (f', text: "{s.text_overlay}"' if s.text_overlay else "")
        for s in shots.shots
    )
    colors = ", ".join(brand.color_palette) if brand.color_palette else "#000000, #FFFFFF"
    copy = "\n".join(f"- {p}" for p in brand.copy_points)
    return f"""Generate a single self-contained HTML file that renders a {brand.target_aspect_ratio} marketing video sequence using CSS animations and GSAP.

Brand: {brand.brand_name}
Tagline: {brand.tagline or ""}
Colors: {colors}
Copy points:
{copy}

Shots to animate ({shots.style.pacing} pacing, {shots.style.transition} transitions):
{shots_desc}

Requirements:
- Single HTML file with all CSS and JS inline
- Use GSAP (load from CDN) for animations
- Each shot auto-advances after its duration
- Aspect ratio {brand.target_aspect_ratio} viewport
- Output ONLY the HTML, no explanation
"""


def _call_llm(prompt: str, cfg: Config) -> str:
    if not cfg.html_gen_api_key:
        logger.warning(
            "HTML_GEN_API_KEY is empty — LLM call will fail. "
            "Set HTML_GEN_API_KEY in .env"
        )

    client = OpenAI(
        base_url=cfg.html_gen_base_url,
        api_key=cfg.html_gen_api_key or "missing",
    )

    try:
        response = client.chat.completions.create(
            model=cfg.html_gen_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=8192,
        )
        return response.choices[0].message.content or ""
    except Exception as exc:
        hint = ""
        exc_lower = str(exc).lower()
        if "auth" in exc_lower or "api key" in exc_lower or "401" in exc_lower:
            hint = " — check HTML_GEN_API_KEY and HTML_GEN_BASE_URL in .env"
        elif "model" in exc_lower or "404" in exc_lower:
            hint = (
                f" — check HTML_GEN_MODEL='{cfg.html_gen_model}' "
                "is supported by your endpoint"
            )
        logger.error("HTML generation LLM call failed: %s%s", exc, hint)
        raise ValueError(f"LLM call failed: {exc}{hint}") from exc


def _is_valid_html(text: str) -> bool:
    return bool(_HTML_RE.search(text))


def generate_html(
    shots: ShotsOutput,
    brand: BrandAssets,
    cfg: Config,
    output_dir: Path = Path("output"),
) -> str:
    prompt = _build_prompt(shots, brand)
    last_raw = ""
    for attempt in range(_MAX_RETRIES + 1):
        last_raw = _call_llm(prompt, cfg)
        if _is_valid_html(last_raw):
            return last_raw
        logger.warning(
            "HTML generation attempt %d/%d did not return valid HTML",
            attempt + 1,
            _MAX_RETRIES + 1,
        )
    debug_dir = output_dir / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    debug_file = debug_dir / f"html_gen_raw_{ts}.txt"
    debug_file.write_text(last_raw, encoding="utf-8")
    raise ValueError(
        f"HTML generation failed after {_MAX_RETRIES + 1} attempts; "
        f"raw LLM output saved to {debug_file}"
    )
