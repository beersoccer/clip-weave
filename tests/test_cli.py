"""Tests for the v6.0 CLI: run, guard, match-assets."""

from pathlib import Path
from unittest.mock import patch
from click.testing import CliRunner
from clip_weave.__main__ import cli


def test_run_command_creates_project(tmp_path):
    runner = CliRunner()
    with patch("clip_weave.__main__.pipeline_run", return_value=tmp_path / "videos" / "proj") as mock_run:
        result = runner.invoke(cli, [
            "run",
            "--message", "小米SU7品牌视频",
            "--project", "su7-test",
            "--videos-dir", str(tmp_path / "videos"),
        ])
    assert result.exit_code == 0, result.output
    mock_run.assert_called_once()
    kwargs = mock_run.call_args[1]
    assert kwargs["project_name"] == "su7-test"
    assert "小米SU7品牌视频" in kwargs["message"]


def test_run_command_with_url(tmp_path):
    runner = CliRunner()
    with patch("clip_weave.__main__.pipeline_run", return_value=tmp_path / "videos" / "proj") as mock_run:
        result = runner.invoke(cli, [
            "run",
            "--url", "https://example.com",
            "--message", "产品发布",
            "--videos-dir", str(tmp_path),
        ])
    assert result.exit_code == 0, result.output
    user_input = mock_run.call_args[1]["user_input"]
    assert "https://example.com" in user_input


def test_guard_command_clean(tmp_path):
    comp_dir = tmp_path / "compositions"
    comp_dir.mkdir()
    (comp_dir / "01.html").write_text("<html><body></body></html>")
    runner = CliRunner()
    result = runner.invoke(cli, ["guard", str(tmp_path)])
    assert result.exit_code == 0
    assert "all clear" in result.output


def test_guard_command_violation(tmp_path):
    comp_dir = tmp_path / "compositions"
    comp_dir.mkdir()
    (comp_dir / "01.html").write_text("<html><body><video src='x.mp4'></video></body></html>")
    runner = CliRunner()
    result = runner.invoke(cli, ["guard", str(tmp_path)])
    assert result.exit_code == 1


def test_guard_command_no_compositions_dir(tmp_path):
    runner = CliRunner()
    result = runner.invoke(cli, ["guard", str(tmp_path)])
    assert result.exit_code == 1
    assert "No compositions/" in result.output
