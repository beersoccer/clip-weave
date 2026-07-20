"""Tests for HyperFrames adapter."""

from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from clip_weave.adapters.hyperframes import render_html_to_video, HyperFramesError

HTML = "<html><body>test</body></html>"


def test_render_returns_mp4_path(tmp_path):
    output_mp4 = tmp_path / "final.mp4"
    mock_result = MagicMock(returncode=0, stderr="")
    with patch("clip_weave.adapters.hyperframes.subprocess.run", return_value=mock_result):
        output_mp4.write_bytes(b"fake")
        with patch("clip_weave.adapters.hyperframes._output_path", return_value=output_mp4):
            result = render_html_to_video(HTML, tmp_path)
    assert result == output_mp4


def test_render_nonzero_exit_raises_and_preserves_frames(tmp_path):
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    (frames_dir / "frame_0001.jpg").write_bytes(b"img")
    mock_result = MagicMock(returncode=1, stderr="chromium error")
    with patch("clip_weave.adapters.hyperframes.subprocess.run", return_value=mock_result):
        with patch("clip_weave.adapters.hyperframes._frames_dir", return_value=frames_dir):
            with pytest.raises(HyperFramesError) as exc_info:
                render_html_to_video(HTML, tmp_path)
    assert "chromium error" in str(exc_info.value)
    assert (frames_dir / "frame_0001.jpg").exists()
