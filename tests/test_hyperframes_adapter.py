"""Tests for the rewritten HyperFrames CLI adapter."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from clip_weave.adapters.hyperframes import (
    HyperFramesError, init, capture, lint, check, render,
)


def _ok(stdout="", stderr=""):
    return MagicMock(returncode=0, stdout=stdout, stderr=stderr)


def _fail(stderr="error"):
    return MagicMock(returncode=1, stdout="", stderr=stderr)


def test_init_skips_when_json_exists(tmp_path):
    (tmp_path / "hyperframes.json").write_text("{}")
    with patch("clip_weave.adapters.hyperframes.subprocess.run") as mock_run:
        init(tmp_path)
    mock_run.assert_not_called()


def test_init_runs_when_no_json(tmp_path):
    with patch("clip_weave.adapters.hyperframes.subprocess.run", return_value=_ok()) as mock_run:
        init(tmp_path)
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "hyperframes" in cmd
    assert "init" in cmd
    assert "--non-interactive" in cmd


def test_init_raises_on_failure(tmp_path):
    with patch("clip_weave.adapters.hyperframes.subprocess.run", return_value=_fail("bad")):
        with pytest.raises(HyperFramesError, match="bad"):
            init(tmp_path)


def test_capture_returns_capture_dir(tmp_path):
    with patch("clip_weave.adapters.hyperframes.subprocess.run", return_value=_ok()) as mock_run:
        result = capture("https://example.com", tmp_path)
    assert result == tmp_path / "capture"
    cmd = mock_run.call_args[0][0]
    assert "capture" in cmd
    assert "https://example.com" in cmd


def test_lint_returns_true_on_success(tmp_path):
    with patch("clip_weave.adapters.hyperframes.subprocess.run",
               return_value=MagicMock(returncode=0, stdout="ok", stderr="")):
        ok, output = lint(tmp_path)
    assert ok is True
    assert "ok" in output


def test_lint_returns_false_on_failure(tmp_path):
    with patch("clip_weave.adapters.hyperframes.subprocess.run",
               return_value=MagicMock(returncode=1, stdout="", stderr="lint error")):
        ok, output = lint(tmp_path)
    assert ok is False
    assert "lint error" in output


def test_check_with_specific_file(tmp_path):
    comp = tmp_path / "compositions" / "01-hero.html"
    comp.parent.mkdir(parents=True)
    comp.write_text("<html></html>")
    with patch("clip_weave.adapters.hyperframes.subprocess.run",
               return_value=MagicMock(returncode=0, stdout="pass", stderr="")) as mock_run:
        ok, _ = check(tmp_path, file=comp)
    assert ok is True
    cmd = mock_run.call_args[0][0]
    assert "01-hero.html" in " ".join(cmd)


def test_render_returns_output_path(tmp_path):
    out = tmp_path / "renders" / "video.mp4"
    out.parent.mkdir(parents=True)
    with patch("clip_weave.adapters.hyperframes.subprocess.run", return_value=_ok()):
        result = render(tmp_path, output=out)
    assert result == out
