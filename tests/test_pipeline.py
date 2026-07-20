import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from clip_weave.schemas.shots import ShotsOutput
from clip_weave.schemas.brand_assets import BrandAssets
from clip_weave.config import Config
from clip_weave.pipeline import analyze, render

FIXTURE_DIR = Path(__file__).parent / "fixtures"
SHOTS = ShotsOutput.model_validate(json.loads((FIXTURE_DIR / "shots.json").read_text()))
BRAND = BrandAssets.model_validate(json.loads((FIXTURE_DIR / "brand_assets.json").read_text()))
CFG = Config(
    anthropic_api_key="k", openai_api_key="k",
    gemini_api_key="k", pexels_api_key="k",
    html_gen_model="claude", scene_threshold=0.35,
)


def test_analyze_returns_and_persists(tmp_path):
    with patch("clip_weave.pipeline.analyze_video", return_value=SHOTS):
        result = analyze("sample.mp4", CFG, output_dir=tmp_path)
    assert isinstance(result, ShotsOutput)
    shots_file = tmp_path / "shots.json"
    assert shots_file.exists()
    loaded = ShotsOutput.model_validate(json.loads(shots_file.read_text()))
    assert loaded.shot_count == SHOTS.shot_count


def test_render_calls_adapters(tmp_path):
    mp4_path = tmp_path / "final.mp4"
    mp4_path.write_bytes(b"fake")
    with patch("clip_weave.pipeline.generate_html", return_value="<html></html>") as mock_html, \
         patch("clip_weave.pipeline.render_html_to_video", return_value=mp4_path) as mock_render:
        result = render(SHOTS, BRAND, CFG, output_dir=tmp_path)
    mock_html.assert_called_once_with(SHOTS, BRAND, CFG, output_dir=tmp_path)
    mock_render.assert_called_once()
    assert result == mp4_path
