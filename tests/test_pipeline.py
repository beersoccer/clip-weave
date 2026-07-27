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


def test_run_skips_intent_when_brief_exists(tmp_path):
    """§4.1.1: existing BRIEF.md → delegate directly, skip intent + factory."""
    videos_dir = tmp_path / "videos"
    project_dir = videos_dir / "existing-proj"
    project_dir.mkdir(parents=True)
    (project_dir / "BRIEF.md").write_text("workflow: product-launch-video\n")

    with patch("clip_weave.pipeline.factory_setup") as mock_factory, \
         patch("clip_weave.pipeline.write_brief") as mock_write, \
         patch("clip_weave.pipeline.print_delegation_instructions"):
        result = run(
            user_input="whatever",
            project_name="existing-proj",
            videos_dir=videos_dir,
        )
    mock_factory.assert_not_called()
    mock_write.assert_not_called()
    assert result == project_dir


def test_run_length_written_to_brief(tmp_path):
    videos_dir = tmp_path / "videos"
    with patch("clip_weave.pipeline.factory_setup"), \
         patch("clip_weave.pipeline.print_delegation_instructions"):
        project_dir = run(
            user_input="品牌视频",
            project_name="len-test",
            videos_dir=videos_dir,
            message="test",
            length="60s",
        )
    brief = (project_dir / "BRIEF.md").read_text()
    assert "length: 60s" in brief


def test_guard_gsap_fixer_does_not_corrupt_non_gsap_objects(tmp_path):
    """GSAP fixer must not rewrite x:/y: in non-GSAP JS objects (regression)."""
    from clip_weave.adapters.rule_guard import _fix_gsap_css_transform_conflict

    html = """<script>
const chartConfig = { x: 50, y: 100, width: 200 };
const svgData = [{ x: 10 }, { x: 20 }];
gsap.to(".el", { x: 30, duration: 1 });
</script>"""
    result = _fix_gsap_css_transform_conflict(html)
    # Non-GSAP objects must be untouched
    assert "chartConfig = { x: 50" in result
    assert "svgData = [{ x: 10 }" in result
    # GSAP call must be rewritten
    assert "xPercent: 30" in result
