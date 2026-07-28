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


def test_guard_gsap_css_conflict_reported_without_auto_fix(tmp_path):
    """gsap_css_transform_conflict is detected but not auto-fixed (semantic safety)."""
    from clip_weave.adapters.rule_guard import scan

    html = """<template>
<style>.el { transform: translateX(-50%); }</style>
<div data-hf-id="x" id="el" class="clip" data-start="0" data-duration="1" data-track-index="0"></div>
<script>
gsap.to("#el", { x: 30, duration: 1 });
</script>
</template>"""
    f = tmp_path / "test.html"
    f.write_text(html)
    result = scan(tmp_path)
    assert any(v.rule_id == "gsap_css_transform_conflict" for v in result.violations)
    assert result.fixed == []   # no auto-fix applied


# ── Image filtering ───────────────────────────────────────────────────────────

def test_filter_removes_noise_but_keeps_logos(tmp_path):
    from clip_weave.core.project_factory import _filter_capture_assets

    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()

    # Noise — should be removed
    noise = [
        "favicon.ico",
        "wechat_qrcode.png",
        "whatsapp.svg",
        "svg-a1b2c3d4.svg",
        "social-icons.png",
        "loader.gif",
    ]
    # Logos — must be preserved even though some have short/simple names
    logos = [
        "logo.svg",           # classic logo filename
        "brand-logo.png",     # brand in name
        "noah-wordmark.svg",  # wordmark
        "company_emblem.png", # emblem
    ]
    # Normal assets — not noise, not logo-flagged
    normal = ["hero-banner.png", "team-photo.jpg"]

    for name in noise + logos + normal:
        (assets_dir / name).write_bytes(b"x" * 100)

    _filter_capture_assets(assets_dir)

    remaining = {f.name for f in assets_dir.iterdir()}
    for name in logos + normal:
        assert name in remaining, f"Expected {name} to be kept"
    for name in noise:
        assert name not in remaining, f"Expected {name} to be removed"


def test_filter_keeps_small_svgs_unconditionally(tmp_path):
    from clip_weave.core.project_factory import _filter_capture_assets

    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    # An SVG with a plain name (not hash-named, no logo keyword) — keep it
    (assets_dir / "arrow-right.svg").write_bytes(b"<svg/>" * 10)
    # A hash-named SVG — remove
    (assets_dir / "svg-deadbeef.svg").write_bytes(b"<svg/>")

    _filter_capture_assets(assets_dir)

    assert (assets_dir / "arrow-right.svg").exists()
    assert not (assets_dir / "svg-deadbeef.svg").exists()


# ── Asset Matcher ─────────────────────────────────────────────────────────────

def test_asset_matcher_bm25_fallback(tmp_path):
    """Without gateway config, should fall back to BM25 and return ranked results."""
    from clip_weave.adapters.asset_matcher import match_assets
    from clip_weave.config import Config

    desc_file = tmp_path / "capture" / "extracted" / "asset-descriptions.md"
    desc_file.parent.mkdir(parents=True)
    desc_file.write_text(
        "- team.jpg — professional executives in formal meeting room\n"
        "- chart.png — bar chart showing revenue growth data\n"
        "- office.jpg — modern corporate office interior\n"
    )

    cfg = Config()  # no gateway configured
    results = match_assets(tmp_path, ["executive team meeting", "financial data"], top_k=2, cfg=cfg)

    assert len(results) == 2
    assert len(results[0]) > 0
    # "team.jpg" should rank higher for the first query
    assert results[0][0]["filename"] == "team.jpg"


def test_asset_matcher_embedding_fallback_to_bm25(tmp_path, monkeypatch):
    """When embedding endpoint fails, should silently fall back to BM25."""
    from clip_weave.adapters import asset_matcher
    from clip_weave.adapters.asset_matcher import match_assets
    from clip_weave.config import Config

    desc_file = tmp_path / "capture" / "extracted" / "asset-descriptions.md"
    desc_file.parent.mkdir(parents=True)
    desc_file.write_text("- logo.svg — gold and blue company logo\n")

    # Simulate embedding gateway failure
    monkeypatch.setattr(asset_matcher, "_call_embedding_gateway", lambda *a, **k: None)

    cfg = Config(
        embedding_base_url="https://embed.example.com/v1/",
        embedding_api_key="test-key",
    )
    results = match_assets(tmp_path, ["brand identity"], top_k=1, cfg=cfg)
    assert len(results) == 1
    assert results[0][0]["filename"] == "logo.svg"
