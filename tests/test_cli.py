import json
from pathlib import Path
from unittest.mock import patch
from click.testing import CliRunner
from clip_weave.__main__ import cli
from clip_weave.schemas.shots import ShotsOutput
from clip_weave.schemas.brand_assets import BrandAssets

FIXTURE_DIR = Path(__file__).parent / "fixtures"
SHOTS = ShotsOutput.model_validate(json.loads((FIXTURE_DIR / "shots.json").read_text()))
BRAND = BrandAssets.model_validate(json.loads((FIXTURE_DIR / "brand_assets.json").read_text()))


def test_analyze_command(tmp_path):
    fake_video = tmp_path / "test.mp4"
    fake_video.write_bytes(b"fake")
    out_file = tmp_path / "shots.json"
    runner = CliRunner()
    with patch("clip_weave.__main__.analyze", return_value=SHOTS) as mock_analyze:
        result = runner.invoke(cli, [
            "analyze", "--video", str(fake_video), "--output", str(out_file)
        ])
    assert result.exit_code == 0, result.output
    mock_analyze.assert_called_once()


def test_run_command(tmp_path):
    fake_video = tmp_path / "test.mp4"
    fake_video.write_bytes(b"fake")
    brand_dir = tmp_path / "brand"
    brand_dir.mkdir()
    (brand_dir / "brand_assets.json").write_text(
        json.dumps({"brand_name": "T", "target_aspect_ratio": "9:16"})
    )
    runner = CliRunner()
    with patch("clip_weave.__main__.analyze", return_value=SHOTS), \
         patch("clip_weave.__main__.render", return_value=tmp_path / "final.mp4"):
        result = runner.invoke(cli, [
            "run", "--video", str(fake_video),
            "--brand", str(brand_dir), "--mode", "hyperframes"
        ])
    assert result.exit_code == 0, result.output


def test_render_command(tmp_path):
    shots_file = tmp_path / "shots.json"
    shots_file.write_text(SHOTS.model_dump_json())
    brand_dir = tmp_path / "brand"
    brand_dir.mkdir()
    (brand_dir / "brand_assets.json").write_text(
        json.dumps({"brand_name": "T", "target_aspect_ratio": "9:16"})
    )
    runner = CliRunner()
    with patch("clip_weave.__main__.render", return_value=tmp_path / "final.mp4"):
        result = runner.invoke(cli, [
            "render", "--shots", str(shots_file),
            "--brand", str(brand_dir), "--mode", "hyperframes"
        ])
    assert result.exit_code == 0, result.output
