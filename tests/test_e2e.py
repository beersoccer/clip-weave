"""End-to-end integration test for the full clip-weave pipeline.

Exercises the full CLI path via CliRunner: __main__.py argument parsing,
env-var loading via load_config(), and Click routing through `run`.

Mocks all external API calls (openai-compatible LLM) and subprocess calls
(FFmpeg, HyperFrames).  Verifies that the `run` command produces a non-empty
output/final.mp4 and writes shots.json.
"""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from clip_weave.__main__ import cli

FIXTURE_DIR = Path(__file__).parent / "fixtures"
TEST_VIDEO = FIXTURE_DIR / "test_5s.mp4"


def _make_openai_mock(content: str) -> MagicMock:
    """Return a mock OpenAI class whose instances return content from chat.completions.create."""
    mock_message = MagicMock()
    mock_message.content = content
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response
    mock_class = MagicMock(return_value=mock_client)
    return mock_class


def _make_anthropic_mock(content: str) -> MagicMock:
    """Return a mock Anthropic class whose instances return content from messages.create."""
    mock_content_block = MagicMock()
    mock_content_block.text = content
    mock_response = MagicMock()
    mock_response.content = [mock_content_block]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    mock_class = MagicMock(return_value=mock_client)
    return mock_class


@pytest.mark.skipif(not TEST_VIDEO.exists(), reason="test_5s.mp4 not generated")
def test_full_pipeline_produces_mp4(tmp_path, monkeypatch):
    """Full CLI `run` command produces a non-empty mp4 and writes shots.json."""

    monkeypatch.chdir(tmp_path)

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

    valid_html = "<html><body><div>Shot 1</div></body></html>"

    # Single subprocess mock: handles ffprobe (duration), ffmpeg frame extraction,
    # and everything else (HyperFrames CLI, FFmpeg merge).
    def subprocess_side_effect(cmd, *args, **kwargs):
        if cmd[0] == "ffprobe":
            return MagicMock(returncode=0, stdout="5.0\n", stderr="")
        cmd_str = " ".join(str(c) for c in cmd)
        if "ffmpeg" in cmd_str:
            out_pattern = next((a for a in cmd if "frame_" in str(a)), None)
            if out_pattern:
                frames_dir = Path(out_pattern).parent
                frames_dir.mkdir(parents=True, exist_ok=True)
                (frames_dir / "frame_0001.jpg").write_bytes(b"\xff\xd8\xff\xe0fake_jpeg")
        return MagicMock(returncode=0, stdout="", stderr="")

    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    mp4_path = output_dir / "final.mp4"
    mp4_path.write_bytes(b"fake-mp4-content")

    mock_analyzer_openai = _make_openai_mock(shots_json)
    mock_html_gen_anthropic = _make_anthropic_mock(valid_html)

    with patch("subprocess.run", side_effect=subprocess_side_effect), \
         patch("clip_weave.adapters.video_analyzer.OpenAI", mock_analyzer_openai), \
         patch("clip_weave.core.html_generator.Anthropic", mock_html_gen_anthropic):

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
                "VIDEO_ANALYSIS_API_KEY": "test-key",
                "HTML_GEN_API_KEY": "test-key",
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
