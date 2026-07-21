"""Tests for video frame analyzer (FFmpeg + LLM multimodal analysis)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from clip_weave.adapters.video_analyzer import (
    VideoAnalysisError,
    _subsample_to,
    analyze_video,
)
from clip_weave.config import Config
from clip_weave.schemas.shots import ShotsOutput

FIXTURE_SHOTS = json.loads(
    (Path(__file__).parent / "fixtures" / "shots.json").read_text()
)


def _make_cfg(**kwargs) -> Config:
    defaults = dict(
        video_analysis_base_url=None,
        video_analysis_api_key="test-key",
        video_analysis_model="gemini-2.5-flash",
        html_gen_base_url=None,
        html_gen_api_key="test-key",
        html_gen_model="claude-sonnet-4-6",
        pexels_api_key="",
        scene_threshold=0.35,
    )
    defaults.update(kwargs)
    return Config(**defaults)


def _make_openai_mock(content: str) -> MagicMock:
    mock_message = MagicMock()
    mock_message.content = content
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response
    return mock_client


def _make_subprocess_side_effect(
    frames_dir: Path,
    duration: str = "30.0",
    frame_count: int = 1,
    ffmpeg_returncode: int = 0,
):
    """
    Build a subprocess.run side_effect that handles all 3 calls in sequence:
      1. ffprobe  → returncode=0, stdout=duration
      2. ffmpeg main extraction → creates frame_count frames in frames_dir
      3. ffmpeg last frame (-sseof) → returncode=0 (no file written)
    """
    call_idx = [0]

    def side_effect(args, **kwargs):
        idx = call_idx[0]
        call_idx[0] += 1

        if args[0] == "ffprobe":
            return MagicMock(returncode=0, stdout=f"{duration}\n", stderr="")

        # ffmpeg calls
        if idx == 1:
            # main extraction
            if ffmpeg_returncode != 0:
                return MagicMock(returncode=ffmpeg_returncode, stdout="", stderr="ffmpeg error")
            frames_dir.mkdir(parents=True, exist_ok=True)
            for i in range(1, frame_count + 1):
                (frames_dir / f"frame_{i:04d}.jpg").write_bytes(b"\xff\xd8\xff\xe0fake")
            return MagicMock(returncode=0, stdout="", stderr="")

        # last-frame append (-sseof)
        return MagicMock(returncode=0, stdout="", stderr="")

    return side_effect


# ── analyze_video integration tests ──────────────────────────────────────────

def test_analyze_video_returns_shots_output(tmp_path):
    frames_dir = tmp_path / "frames"
    mock_client = _make_openai_mock(json.dumps(FIXTURE_SHOTS))
    side_effect = _make_subprocess_side_effect(frames_dir, frame_count=1)

    with patch("clip_weave.adapters.video_analyzer.subprocess.run", side_effect=side_effect), \
         patch("clip_weave.adapters.video_analyzer.OpenAI", return_value=mock_client):
        result = analyze_video("test.mp4", cfg=_make_cfg(), frames_dir=frames_dir)

    assert isinstance(result, ShotsOutput)
    assert result.shot_count == 2


def test_analyze_video_ffmpeg_failure_raises(tmp_path):
    frames_dir = tmp_path / "frames"
    side_effect = _make_subprocess_side_effect(frames_dir, ffmpeg_returncode=1)

    with patch("clip_weave.adapters.video_analyzer.subprocess.run", side_effect=side_effect):
        with pytest.raises(VideoAnalysisError) as exc_info:
            analyze_video("test.mp4", cfg=_make_cfg(), frames_dir=frames_dir)

    assert exc_info.value.stderr == "ffmpeg error"


def test_analyze_video_ffprobe_failure_raises(tmp_path):
    frames_dir = tmp_path / "frames"

    def side_effect(args, **kwargs):
        return MagicMock(returncode=1, stdout="", stderr="ffprobe error")

    with patch("clip_weave.adapters.video_analyzer.subprocess.run", side_effect=side_effect):
        with pytest.raises(VideoAnalysisError, match="ffprobe"):
            analyze_video("test.mp4", cfg=_make_cfg(), frames_dir=frames_dir)


def test_analyze_video_no_frames_raises(tmp_path):
    frames_dir = tmp_path / "frames"
    # ffprobe succeeds, ffmpeg succeeds but writes no frames
    side_effect = _make_subprocess_side_effect(frames_dir, frame_count=0)

    with patch("clip_weave.adapters.video_analyzer.subprocess.run", side_effect=side_effect):
        with pytest.raises(VideoAnalysisError, match="No frames"):
            analyze_video("test.mp4", cfg=_make_cfg(), frames_dir=frames_dir)


def test_analyze_video_invalid_json_raises(tmp_path):
    frames_dir = tmp_path / "frames"
    mock_client = _make_openai_mock("not valid json")
    side_effect = _make_subprocess_side_effect(frames_dir, frame_count=1)

    with patch("clip_weave.adapters.video_analyzer.subprocess.run", side_effect=side_effect), \
         patch("clip_weave.adapters.video_analyzer.OpenAI", return_value=mock_client):
        with pytest.raises(VideoAnalysisError, match="invalid JSON"):
            analyze_video("test.mp4", cfg=_make_cfg(), frames_dir=frames_dir)


def test_analyze_video_api_failure_raises(tmp_path):
    frames_dir = tmp_path / "frames"
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = Exception("API quota exceeded")
    side_effect = _make_subprocess_side_effect(frames_dir, frame_count=1)

    with patch("clip_weave.adapters.video_analyzer.subprocess.run", side_effect=side_effect), \
         patch("clip_weave.adapters.video_analyzer.OpenAI", return_value=mock_client):
        with pytest.raises(VideoAnalysisError, match="LLM API call failed"):
            analyze_video("test.mp4", cfg=_make_cfg(), frames_dir=frames_dir)


def test_analyze_video_json_in_markdown_codeblock(tmp_path):
    frames_dir = tmp_path / "frames"
    mock_client = _make_openai_mock(f"```json\n{json.dumps(FIXTURE_SHOTS)}\n```")
    side_effect = _make_subprocess_side_effect(frames_dir, frame_count=1)

    with patch("clip_weave.adapters.video_analyzer.subprocess.run", side_effect=side_effect), \
         patch("clip_weave.adapters.video_analyzer.OpenAI", return_value=mock_client):
        result = analyze_video("test.mp4", cfg=_make_cfg(), frames_dir=frames_dir)

    assert isinstance(result, ShotsOutput)


def test_analyze_video_auth_error_hint(tmp_path):
    frames_dir = tmp_path / "frames"
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = Exception("401 Unauthorized: invalid api key")
    side_effect = _make_subprocess_side_effect(frames_dir, frame_count=1)

    with patch("clip_weave.adapters.video_analyzer.subprocess.run", side_effect=side_effect), \
         patch("clip_weave.adapters.video_analyzer.OpenAI", return_value=mock_client):
        with pytest.raises(VideoAnalysisError) as exc_info:
            analyze_video("test.mp4", cfg=_make_cfg(), frames_dir=frames_dir)

    assert "VIDEO_ANALYSIS_API_KEY" in str(exc_info.value)


# ── _subsample_to unit tests ──────────────────────────────────────────────────

def test_subsample_to_preserves_first_and_last(tmp_path):
    frames = []
    for i in range(1, 11):
        p = tmp_path / f"frame_{i:04d}.jpg"
        p.write_bytes(b"x")
        frames.append(p)

    _subsample_to(frames, keep=3)

    remaining = sorted(tmp_path.glob("frame_*.jpg"))
    assert remaining[0].name == "frame_0001.jpg"
    assert remaining[-1].name == "frame_0010.jpg"
    assert len(remaining) == 3


def test_subsample_to_no_op_when_keep_gte_n(tmp_path):
    frames = []
    for i in range(1, 6):
        p = tmp_path / f"frame_{i:04d}.jpg"
        p.write_bytes(b"x")
        frames.append(p)

    _subsample_to(frames, keep=10)

    assert len(list(tmp_path.glob("frame_*.jpg"))) == 5


def test_subsample_to_keep_one(tmp_path):
    frames = []
    for i in range(1, 6):
        p = tmp_path / f"frame_{i:04d}.jpg"
        p.write_bytes(b"x")
        frames.append(p)

    _subsample_to(frames, keep=1)

    remaining = list(tmp_path.glob("frame_*.jpg"))
    assert len(remaining) == 1
    assert remaining[0].name == "frame_0001.jpg"


def test_subsample_to_distributes_evenly(tmp_path):
    frames = []
    for i in range(1, 11):
        p = tmp_path / f"frame_{i:04d}.jpg"
        p.write_bytes(b"x")
        frames.append(p)

    _subsample_to(frames, keep=5)

    remaining = sorted(tmp_path.glob("frame_*.jpg"))
    assert len(remaining) == 5
    assert remaining[0].name == "frame_0001.jpg"
    assert remaining[-1].name == "frame_0010.jpg"
