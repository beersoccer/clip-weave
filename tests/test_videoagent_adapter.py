"""Tests for VideoAgent adapter (Gemini-based implementation)."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from clip_weave.adapters.videoagent import analyze_video, VideoAnalysisError
from clip_weave.schemas.shots import ShotsOutput

FIXTURE_SHOTS = json.loads(
    (Path(__file__).parent / "fixtures" / "shots.json").read_text()
)


def test_analyze_video_returns_shots_output(tmp_path):
    frames_dir = tmp_path / "frames"

    def ffmpeg_write_frame(*args, **kwargs):
        # Simulate FFmpeg writing a frame into frames_dir (which was just recreated)
        frames_dir.mkdir(parents=True, exist_ok=True)
        (frames_dir / "frame_0001.jpg").write_bytes(b"\xff\xd8\xff\xe0fake_jpeg")
        return MagicMock(returncode=0, stdout="", stderr="")

    mock_response = MagicMock()
    mock_response.text = json.dumps(FIXTURE_SHOTS)
    mock_model = MagicMock()
    mock_model.generate_content.return_value = mock_response
    mock_genai = MagicMock()
    mock_genai.GenerativeModel.return_value = mock_model

    with patch("clip_weave.adapters.videoagent.subprocess.run", side_effect=ffmpeg_write_frame), \
         patch("clip_weave.adapters.videoagent.genai", mock_genai):
        result = analyze_video("test.mp4", frames_dir=frames_dir)

    assert isinstance(result, ShotsOutput)
    assert result.shot_count == 2


def test_analyze_video_ffmpeg_failure_raises(tmp_path):
    mock_ffmpeg = MagicMock(returncode=1, stdout="", stderr="ffmpeg error")
    with patch("clip_weave.adapters.videoagent.subprocess.run", return_value=mock_ffmpeg):
        with pytest.raises(VideoAnalysisError) as exc_info:
            analyze_video("test.mp4", frames_dir=tmp_path / "frames")
    assert exc_info.value.stderr == "ffmpeg error"


def test_analyze_video_invalid_json_raises(tmp_path):
    frames_dir = tmp_path / "frames"

    def ffmpeg_write_frame(*args, **kwargs):
        frames_dir.mkdir(parents=True, exist_ok=True)
        (frames_dir / "frame_0001.jpg").write_bytes(b"\xff\xd8\xff\xe0fake")
        return MagicMock(returncode=0, stdout="", stderr="")

    mock_response = MagicMock()
    mock_response.text = "not valid json"
    mock_model = MagicMock()
    mock_model.generate_content.return_value = mock_response
    mock_genai = MagicMock()
    mock_genai.GenerativeModel.return_value = mock_model

    with patch("clip_weave.adapters.videoagent.subprocess.run", side_effect=ffmpeg_write_frame), \
         patch("clip_weave.adapters.videoagent.genai", mock_genai):
        with pytest.raises(VideoAnalysisError, match="invalid JSON"):
            analyze_video("test.mp4", frames_dir=frames_dir)


def test_analyze_video_gemini_api_failure_raises(tmp_path):
    frames_dir = tmp_path / "frames"

    def ffmpeg_write_frame(*args, **kwargs):
        frames_dir.mkdir(parents=True, exist_ok=True)
        (frames_dir / "frame_0001.jpg").write_bytes(b"\xff\xd8\xff\xe0fake_jpeg")
        return MagicMock(returncode=0, stdout="", stderr="")

    mock_model = MagicMock()
    mock_model.generate_content.side_effect = Exception("API quota exceeded")
    mock_genai = MagicMock()
    mock_genai.GenerativeModel.return_value = mock_model

    with patch("clip_weave.adapters.videoagent.subprocess.run", side_effect=ffmpeg_write_frame), \
         patch("clip_weave.adapters.videoagent.genai", mock_genai):
        with pytest.raises(VideoAnalysisError, match="Gemini API"):
            analyze_video("test.mp4", frames_dir=frames_dir)


def test_analyze_video_json_in_markdown_codeblock(tmp_path):
    """Gemini often returns JSON wrapped in ```json ... ``` blocks."""
    frames_dir = tmp_path / "frames"

    def ffmpeg_write_frame(*args, **kwargs):
        frames_dir.mkdir(parents=True, exist_ok=True)
        (frames_dir / "frame_0001.jpg").write_bytes(b"\xff\xd8\xff\xe0fake_jpeg")
        return MagicMock(returncode=0, stdout="", stderr="")

    mock_response = MagicMock()
    mock_response.text = f"```json\n{json.dumps(FIXTURE_SHOTS)}\n```"
    mock_model = MagicMock()
    mock_model.generate_content.return_value = mock_response
    mock_genai = MagicMock()
    mock_genai.GenerativeModel.return_value = mock_model

    with patch("clip_weave.adapters.videoagent.subprocess.run", side_effect=ffmpeg_write_frame), \
         patch("clip_weave.adapters.videoagent.genai", mock_genai):
        result = analyze_video("test.mp4", frames_dir=frames_dir)

    assert isinstance(result, ShotsOutput)
    assert result.shot_count == 2


def test_analyze_video_no_frames_raises(tmp_path):
    frames_dir = tmp_path / "frames"
    mock_ffmpeg = MagicMock(returncode=0, stdout="", stderr="")
    with patch("clip_weave.adapters.videoagent.subprocess.run", return_value=mock_ffmpeg):
        with pytest.raises(VideoAnalysisError, match="No frames"):
            analyze_video("test.mp4", frames_dir=frames_dir)


def test_analyze_video_fallback_fps_extraction(tmp_path):
    """When scene-detection yields 0 frames, fallback to fps=1 extraction."""
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    # No frames initially — simulate scene extraction producing nothing,
    # then fallback writes a frame.
    mock_ffmpeg_scene = MagicMock(returncode=0, stdout="", stderr="")
    mock_ffmpeg_fallback = MagicMock(returncode=0, stdout="", stderr="")

    call_count = 0

    def ffmpeg_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Scene extraction: don't write any frames
            return mock_ffmpeg_scene
        else:
            # Fallback fps=1: write a frame
            (frames_dir / "frame_0001.jpg").write_bytes(b"\xff\xd8\xff\xe0fake_jpeg")
            return mock_ffmpeg_fallback

    mock_response = MagicMock()
    mock_response.text = json.dumps(FIXTURE_SHOTS)
    mock_model = MagicMock()
    mock_model.generate_content.return_value = mock_response
    mock_genai = MagicMock()
    mock_genai.GenerativeModel.return_value = mock_model

    with patch("clip_weave.adapters.videoagent.subprocess.run", side_effect=ffmpeg_side_effect), \
         patch("clip_weave.adapters.videoagent.genai", mock_genai):
        result = analyze_video("test.mp4", frames_dir=frames_dir)

    assert call_count == 2  # scene-detect + fallback
    assert isinstance(result, ShotsOutput)
