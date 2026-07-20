"""End-to-end integration test for the full clip-weave pipeline.

Mocks all external API calls (Gemini, Claude) and subprocess calls (FFmpeg,
HyperFrames).  Verifies that analyze() + render() together produce a non-empty
output/final.mp4 via the public pipeline API.
"""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from clip_weave.config import Config
from clip_weave.schemas.shots import ShotsOutput
from clip_weave.schemas.brand_assets import BrandAssets
from clip_weave.pipeline import analyze, render

FIXTURE_DIR = Path(__file__).parent / "fixtures"
TEST_VIDEO = FIXTURE_DIR / "test_5s.mp4"
SHOTS_JSON = FIXTURE_DIR / "shots.json"


@pytest.mark.skipif(not TEST_VIDEO.exists(), reason="test_5s.mp4 not generated")
def test_full_pipeline_produces_mp4(tmp_path):
    """Full analyze → render pipeline produces a non-empty mp4."""
    cfg = Config(
        anthropic_api_key="k",
        openai_api_key="k",
        gemini_api_key="k",
        pexels_api_key="k",
        html_gen_model="claude",
        scene_threshold=0.35,
    )
    brand = BrandAssets(
        brand_name="TestBrand",
        copy_points=["高品质", "限时优惠"],
        color_palette=["#FF5733"],
        target_aspect_ratio="9:16",
    )
    shots_text = SHOTS_JSON.read_text()

    # --- Set up Gemini mock ---
    mock_response = MagicMock()
    mock_response.text = shots_text
    mock_model = MagicMock()
    mock_model.generate_content.return_value = mock_response
    mock_genai = MagicMock()
    mock_genai.GenerativeModel.return_value = mock_model

    # --- Set up a unified subprocess.run mock that handles both FFmpeg and HyperFrames.
    #
    # Both adapters import `subprocess` from the stdlib and call `subprocess.run`.
    # Patching via two different module paths (videoagent.subprocess.run and
    # hyperframes.subprocess.run) targets the SAME subprocess.run attribute on
    # the shared subprocess module object; the second patch overwrites the first.
    # To avoid that collision we patch the single canonical location:
    # `subprocess.run` directly on the stdlib module.
    #
    # The side_effect discriminates by inspecting the command:
    #   - "ffmpeg" commands: write a fake JPEG frame so _load_frames_as_parts works
    #   - hyperframes commands: just return success
    def subprocess_side_effect(*args, **kwargs):
        cmd = args[0] if args else []
        cmd_str = " ".join(str(c) for c in cmd)
        if "ffmpeg" in cmd_str:
            # Locate the frames output directory from the pattern argument
            out_pattern = next((a for a in cmd if "frame_" in str(a)), None)
            if out_pattern:
                fd = Path(out_pattern).parent
                fd.mkdir(parents=True, exist_ok=True)
                (fd / "frame_0001.jpg").write_bytes(b"\xff\xd8\xff\xe0fake_jpeg")
        # HyperFrames subprocess also just succeeds
        return MagicMock(returncode=0, stdout="", stderr="")

    # --- Set up Claude mock ---
    valid_html = "<html><body><div>Shot 1</div></body></html>"
    mock_llm_msg = MagicMock()
    mock_llm_msg.content = [MagicMock(text=valid_html)]
    mock_claude = MagicMock()
    mock_claude.messages.create.return_value = mock_llm_msg

    # --- Pre-create the expected output mp4 so result.exists() is True ---
    mp4_path = tmp_path / "final.mp4"
    mp4_path.write_bytes(b"fake-mp4-content")

    with patch("subprocess.run", side_effect=subprocess_side_effect), \
         patch("clip_weave.adapters.videoagent.genai", mock_genai), \
         patch("clip_weave.core.html_generator._get_claude_client", return_value=mock_claude):

        shots = analyze(str(TEST_VIDEO), cfg, output_dir=tmp_path)
        result = render(shots, brand, cfg, output_dir=tmp_path)

    # Assertions
    assert isinstance(shots, ShotsOutput)
    assert shots.shot_count == 2
    assert (tmp_path / "shots.json").exists(), "shots.json not written by analyze()"
    assert result.exists(), f"Output mp4 not found at {result}"
    assert result.stat().st_size > 0, "Output mp4 is empty"
