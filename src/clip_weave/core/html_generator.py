import re
from datetime import datetime
from pathlib import Path
import anthropic
import openai
from clip_weave.schemas.shots import ShotsOutput
from clip_weave.schemas.brand_assets import BrandAssets
from clip_weave.config import Config

_HTML_RE = re.compile(r"<html[\s>]", re.IGNORECASE)
_MAX_RETRIES = 2


def _get_claude_client(api_key: str) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=api_key)


def _get_openai_client(api_key: str) -> openai.OpenAI:
    return openai.OpenAI(api_key=api_key)


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
    if cfg.html_gen_model == "claude":
        client = _get_claude_client(cfg.anthropic_api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    client = _get_openai_client(cfg.openai_api_key)
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=4096,
    )
    return response.choices[0].message.content or ""


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
    debug_dir = output_dir / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    (debug_dir / f"html_gen_raw_{ts}.txt").write_text(last_raw, encoding="utf-8")
    raise ValueError(f"HTML generation failed after {_MAX_RETRIES + 1} attempts; raw saved to {debug_dir}")
