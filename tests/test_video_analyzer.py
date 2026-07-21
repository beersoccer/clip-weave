"""Tests for video frame analyzer (FFmpeg + LLM multimodal analysis)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from clip_weave.adapters.video_analyzer import VideoAnalysisError, analyze_video
from clip_weave.config import Config
from clip_weave.schemas.shots import ShotsOutput

FIXTURE_SHOTS = json.loads(
    (Path(__file__).parent / "fixtures" / "shots.json").read_text()
)


def _make_cfg(**kwargs) -> Config:
    defaults = dict(
        video_analysis_base_url=None,
        video_analysis_api_key="test-key",
        video_analysis_model="gemini-2.0-flash-exp",
        html_gen_base_url=None,
        html_gen_api_key="test-key",
        html_gen_model="claude-sonnet-4-6",
        pexels_api_key="",
        scene_threshold=0.35,
    )
    defaults.update(kwargs)
    return Config(**defaults)


def _make_openai_mock(content: str) -> MagicMock:
    """Return a mock OpenAI client whose chat.completions.create returns content."""
    mock_message = MagicMock()
    mock_message.content = content
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response
    return mock_client


def test_analyze_video_returns_shots_output(tmp_path):
    frames_dir = tmp_path / "frames"

    def ffmpeg_write_frame(*args, **kwargs):
        frames_dir.mkdir(parents=True, exist_ok=True)
        (frames_dir / "frame_0001.jpg").write_bytes(b"\xff\xd8\xff\xe0fake_jpeg")
        return MagicMock(returncode=0, stdout="", stderr="")

    mock_client = _make_openai_mock(json.dumps(FIXTURE_SHOTS))

    with patch("clip_weave.adapters.video_analyzer.subprocess.run", side_effect=ffmpeg_write_frame), \
         patch("clip_weave.adapters.video_analyzer.OpenAI", return_value=mock_client):
        result = analyze_video("test.mp4", cfg=_make_cfg(), frames_dir=frames_dir)

    assert isinstance(result, ShotsOutput)
    assert result.shot_count == 2


def test_analyze_video_ffmpeg_failure_raises(tmp_path):
    mock_ffmpeg = MagicMock(returncode=1, stdout="", stderr="ffmpeg error")
    with patch("clip_weave.adapters.video_analyzer.subprocess.run", return_value=mock_ffmpeg):
        with pytest.raises(VideoAnalysisError) as exc_info:
            analyze_video("test.mp4", cfg=_make_cfg(), frames_dir=tmp_path / "frames")
    assert exc_info.value.stderr == "ffmpeg error"


def test_analyze_video_invalid_json_raises(tmp_path):
    frames_dir = tmp_path / "frames"

    def ffmpeg_write_frame(*args, **kwargs):
        frames_dir.mkdir(parents=True, exist_ok=True)
        (frames_dir / "frame_0001.jpg").write_bytes(b"\xff\xd8\xff\xe0fake")
        return MagicMock(returncode=0, stdout="", stderr="")

    mock_client = _make_openai_mock("not valid json")

    with patch("clip_weave.adapters.video_analyzer.subprocess.run", side_effect=ffmpeg_write_frame), \
         patch("clip_weave.adapters.video_analyzer.OpenAI", return_value=mock_client):
        with pytest.raises(VideoAnalysisError, match="invalid JSON"):
            analyze_video("test.mp4", cfg=_make_cfg(), frames_dir=frames_dir)


def test_analyze_video_api_failure_raises(tmp_path):
    frames_dir = tmp_path / "frames"

    def ffmpeg_write_frame(*args, **kwargs):
        frames_dir.mkdir(parents=True, exist_ok=True)
        (frames_dir / "frame_0001.jpg").write_bytes(b"\xff\xd8\xff\xe0fake_jpeg")
        return MagicMock(returncode=0, stdout="", stderr="")

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = Exception("API quota exceeded")

    with patch("clip_weave.adapters.video_analyzer.subprocess.run", side_effect=ffmpeg_write_frame), \
         patch("clip_weave.adapters.video_analyzer.OpenAI", return_value=mock_client):
        with pytest.raises(VideoAnalysisError, match="LLM API call failed"):
            analyze_video("test.mp4", cfg=_make_cfg(), frames_dir=frames_dir)


def test_analyze_video_json_in_markdown_codeblock(tmp_path):
    """LLMs often return JSON wrapped in ```json ... ``` blocks."""
    frames_dir = tmp_path / "frames"

    def ffmpeg_write_frame(*args, **kwargs):
        frames_dir.mkdir(parents=True, exist_ok=True)
        (frames_dir / "frame_0001.jpg").write_bytes(b"\xff\xd8\xff\xe0fake_jpeg")
        return MagicMock(returncode=0, stdout="", stderr="")

    mock_client = _make_openai_mock(f"```json\n{json.dumps(FIXTURE_SHOTS)}\n```")

    with patch("clip_weave.adapters.video_analyzer.subprocess.run", side_effect=ffmpeg_write_frame), \
         patch("clip_weave.adapters.video_analyzer.OpenAI", return_value=mock_client):
        result = analyze_video("test.mp4", cfg=_make_cfg(), frames_dir=frames_dir)

    assert isinstance(result, ShotsOutput)
    assert result.shot_count == 2


def test_analyze_video_no_frames_raises(tmp_path):
    frames_dir = tmp_path / "frames"
    mock_ffmpeg = MagicMock(returncode=0, stdout="", stderr="")
    with patch("clip_weave.adapters.video_analyzer.subprocess.run", return_value=mock_ffmpeg):
        with pytest.raises(VideoAnalysisError, match="No frames"):
            analyze_video("test.mp4", cfg=_make_cfg(), frames_dir=frames_dir)


def test_analyze_video_fallback_fps_extraction(tmp_path):
    """When scene-detection yields 0 frames, fallback to fps=1 extraction."""
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    call_count = 0

    def ffmpeg_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return MagicMock(returncode=0, stdout="", stderr="")
        (frames_dir / "frame_0001.jpg").write_bytes(b"\xff\xd8\xff\xe0fake_jpeg")
        return MagicMock(returncode=0, stdout="", stderr="")

    mock_client = _make_openai_mock(json.dumps(FIXTURE_SHOTS))

    with patch("clip_weave.adapters.video_analyzer.subprocess.run", side_effect=ffmpeg_side_effect), \
         patch("clip_weave.adapters.video_analyzer.OpenAI", return_value=mock_client):
        result = analyze_video("test.mp4", cfg=_make_cfg(), frames_dir=frames_dir)

    assert call_count == 2
    assert isinstance(result, ShotsOutput)


def test_analyze_video_auth_error_hint(tmp_path):
    """Auth errors should include a hint pointing to the relevant env vars."""
    frames_dir = tmp_path / "frames"

    def ffmpeg_write_frame(*args, **kwargs):
        frames_dir.mkdir(parents=True, exist_ok=True)
        (frames_dir / "frame_0001.jpg").write_bytes(b"\xff\xd8\xff\xe0fake_jpeg")
        return MagicMock(returncode=0, stdout="", stderr="")

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = Exception("401 Unauthorized: invalid api key")

    with patch("clip_weave.adapters.video_analyzer.subprocess.run", side_effect=ffmpeg_write_frame), \
         patch("clip_weave.adapters.video_analyzer.OpenAI", return_value=mock_client):
        with pytest.raises(VideoAnalysisError) as exc_info:
            analyze_video("test.mp4", cfg=_make_cfg(), frames_dir=frames_dir)

    assert "VIDEO_ANALYSIS_API_KEY" in str(exc_info.value)
