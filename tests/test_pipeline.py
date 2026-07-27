"""Tests for the v6.0 pipeline: Intent → Factory → Asset Match → Delegate."""

from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from clip_weave.pipeline import run, guard


def test_run_creates_brief_md(tmp_path):
    videos_dir = tmp_path / "videos"
    with patch("clip_weave.pipeline.factory_setup"), \
         patch("clip_weave.pipeline.print_delegation_instructions"):
        project_dir = run(
            user_input="品牌视频",
            project_name="test-proj",
            videos_dir=videos_dir,
            message="小米SU7",
        )
    assert (project_dir / "BRIEF.md").exists()
    brief_text = (project_dir / "BRIEF.md").read_text()
    assert "小米SU7" in brief_text


def test_run_routes_url_to_product_launch(tmp_path):
    videos_dir = tmp_path / "videos"
    with patch("clip_weave.pipeline.factory_setup"), \
         patch("clip_weave.pipeline.print_delegation_instructions"):
        project_dir = run(
            user_input="https://xiaomiev.com/su7",
            project_name="su7",
            videos_dir=videos_dir,
            message="小米SU7",
        )
    brief = (project_dir / "BRIEF.md").read_text()
    assert "product-launch-video" in brief


def test_run_text_only_routes_to_faceless(tmp_path):
    videos_dir = tmp_path / "videos"
    with patch("clip_weave.pipeline.factory_setup"), \
         patch("clip_weave.pipeline.print_delegation_instructions"):
        project_dir = run(
            user_input="解说视频 教程",
            project_name="explainer",
            videos_dir=videos_dir,
            message="什么是量子计算",
        )
    brief = (project_dir / "BRIEF.md").read_text()
    assert "faceless-explainer" in brief


def test_guard_returns_true_on_clean_dir(tmp_path):
    comp_dir = tmp_path / "compositions"
    comp_dir.mkdir()
    (comp_dir / "01-hero.html").write_text("<html><body><div id='hero'></div></body></html>")
    result = guard(comp_dir, project_dir=tmp_path)
    assert result is True


def test_guard_detects_media_in_composition(tmp_path):
    comp_dir = tmp_path / "compositions"
    comp_dir.mkdir()
    (comp_dir / "01-hero.html").write_text(
        "<html><body><video src='hero.mp4'></video></body></html>"
    )
    result = guard(comp_dir, project_dir=tmp_path)
    assert result is False
