"""End-to-end integration test for the full clip-weave pipeline.

Exercises the full CLI path via CliRunner: __main__.py argument parsing,
env-var loading via load_config(), and Click routing through `run`.

Mocks all external API calls (Gemini, Claude) and subprocess calls (FFmpeg,
HyperFrames).  Verifies that the `run` command produces a non-empty
output/final.mp4 and writes shots.json.
"""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from clip_weave.__main__ import cli

FIXTURE_DIR = Path(__file__).parent / "fixtures"
TEST_VIDEO = FIXTURE_DIR / "test_5s.mp4"


@pytest.mark.skipif(not TEST_VIDEO.exists(), reason="test_5s.mp4 not generated")
def test_full_pipeline_produces_mp4(tmp_path, monkeypatch):
    """Full CLI `run` command produces a non-empty mp4 and writes shots.json."""

    # Change working directory to tmp_path so the default output/ dir lands there.
    monkeypatch.chdir(tmp_path)

    # --- Gemini mock ---
    shots_json = json.dumps({
        "style": {
            "pacing": "fast",
            "color_tone": "warm",
            "typography": "sans-serif",
            "transition": "cut",
            "aspect_ratio": "9:16",
        },
        "shots": [
            {
                "index": 0,
                "start": 0.0,
                "end": 2.0,
                "duration": 2.0,
                "type": "hook",
                "composition": "wide",
                "text_overlay": None,
                "visual_element": "product",
                "audio_cue": None,
            }
        ],
        "narrative_structure": "AIDA",
        "total_duration": 2.0,
        "shot_count": 1,
    })
    mock_response = MagicMock()
    mock_response.text = shots_json
    mock_model = MagicMock()
    mock_model.generate_content.return_value = mock_response
    mock_genai = MagicMock()
    mock_genai.GenerativeModel.return_value = mock_model

    # --- Unified subprocess mock ---
    #
    # Both adapters import `subprocess` and call `subprocess.run`.
    # Patching via two different module paths
    # (clip_weave.adapters.videoagent.subprocess.run and
    #  clip_weave.adapters.hyperframes.subprocess.run) both resolve to
    # setting the `run` attribute on the same shared subprocess module object.
    # Nested patch() calls stack: the second patch saves the first mock as its
    # "original" to restore on teardown, so during the `with` block only the
    # second (innermost) mock is active.  Per-module patches are therefore NOT
    # independent for attributes that live on a shared module object.
    #
    # The correct approach is a single patch at the canonical location that
    # handles all callers, with a side_effect that discriminates by command:
    #   - "ffmpeg" commands: write a fake JPEG frame so _load_frames_as_parts works
    #   - everything else (hyperframes CLI): just return success
    def subprocess_side_effect(cmd, *args, **kwargs):
        cmd_str = " ".join(str(c) for c in cmd)
        if "ffmpeg" in cmd_str:
            out_pattern = next((a for a in cmd if "frame_" in str(a)), None)
            if out_pattern:
                frames_dir = Path(out_pattern).parent
                frames_dir.mkdir(parents=True, exist_ok=True)
                (frames_dir / "frame_0001.jpg").write_bytes(b"\xff\xd8\xff\xe0fake_jpeg")
        return MagicMock(returncode=0, stdout="", stderr="")

    # --- Claude mock ---
    valid_html = "<html><body><div>Shot 1</div></body></html>"
    mock_llm_msg = MagicMock()
    mock_llm_msg.content = [MagicMock(text=valid_html)]
    mock_claude = MagicMock()
    mock_claude.messages.create.return_value = mock_llm_msg

    # --- Pre-create output mp4 (subprocess mock won't actually write it) ---
    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    mp4_path = output_dir / "final.mp4"
    mp4_path.write_bytes(b"fake-mp4-content")

    with patch("subprocess.run", side_effect=subprocess_side_effect), \
         patch("clip_weave.adapters.videoagent.genai", mock_genai), \
         patch("clip_weave.core.html_generator._get_claude_client", return_value=mock_claude):

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "run",
                "--video", str(TEST_VIDEO),
                "--brand", str(FIXTURE_DIR),
                "--mode", "hyperframes",
            ],
            env={
                "GEMINI_API_KEY": "test-key",
                "OPENAI_API_KEY": "test-key",
                "ANTHROPIC_API_KEY": "test-key",
                "PEXELS_API_KEY": "test-key",
            },
            catch_exceptions=False,
        )

    assert result.exit_code == 0, (
        f"CLI exited with code {result.exit_code}:\n{result.output}"
    )
    assert mp4_path.exists(), f"Output mp4 not found at {mp4_path}"
    assert mp4_path.stat().st_size > 0, "Output mp4 is empty"
    assert (output_dir / "shots.json").exists(), "shots.json not written by analyze()"
