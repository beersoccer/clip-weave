import json
from pathlib import Path
from clip_weave.adapters.video_analyzer import analyze_video
from clip_weave.adapters.hyperframes import render_html_to_video
from clip_weave.core.html_generator import generate_html
from clip_weave.schemas.shots import ShotsOutput
from clip_weave.schemas.brand_assets import BrandAssets
from clip_weave.config import Config


def analyze(
    video_path: str,
    cfg: Config,
    output_dir: Path = Path("output"),
) -> ShotsOutput:
    shots = analyze_video(
        video_path,
        scene_threshold=cfg.scene_threshold,
        gemini_api_key=cfg.gemini_api_key,
        frames_dir=output_dir / "frames",
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "shots.json").write_text(
        shots.model_dump_json(indent=2), encoding="utf-8"
    )
    return shots


def render(
    shots: ShotsOutput,
    brand: BrandAssets,
    cfg: Config,
    output_dir: Path = Path("output"),
) -> Path:
    html = generate_html(shots, brand, cfg, output_dir=output_dir)
    return render_html_to_video(html, output_dir)
