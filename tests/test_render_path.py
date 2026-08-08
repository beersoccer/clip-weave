"""Tests for the project-level Production Profile contract."""

import logging

import pytest

from clip_weave.core import render_path as rp


def _brief(tmp_path, body: str, name: str = "BRIEF.md"):
    (tmp_path / name).write_text(body, encoding="utf-8")
    return tmp_path


def test_unset_when_there_is_no_brief(tmp_path):
    assert rp.resolve(tmp_path) == (None, "unset")


def test_unset_when_brief_has_no_profile(tmp_path):
    _brief(tmp_path, "---\nworkflow: product-launch-video\n---\n")
    assert rp.resolve(tmp_path) == (None, "unset")


@pytest.mark.parametrize("profile", ["html_launch", "t2v_brand_film"])
def test_profile_resolves_from_canonical_frontmatter(tmp_path, profile):
    _brief(tmp_path, f"---\nproduction_profile: {profile}\n---\n")
    assert rp.resolve(tmp_path) == (profile, "BRIEF.md:production_profile")


def test_profile_is_case_insensitive_and_dequoted(tmp_path):
    _brief(tmp_path, '---\nproduction_profile: "T2V_BRAND_FILM"\n---\n')
    assert rp.resolve(tmp_path)[0] == "t2v_brand_film"


def test_profile_accepts_a_yaml_inline_comment(tmp_path):
    _brief(tmp_path, "---\nproduction_profile: html_launch  # default profile\n---\n")
    assert rp.resolve(tmp_path) == ("html_launch", "BRIEF.md:production_profile")


def test_legacy_render_is_read_with_a_migration_warning(tmp_path, caplog):
    _brief(tmp_path, "---\nrender: t2v\n---\n")
    with caplog.at_level(logging.WARNING, logger="clip_weave.core.render_path"):
        profile, source = rp.resolve(tmp_path)
    assert (profile, source) == ("t2v_brand_film", "BRIEF.md:render")
    assert "production_profile" in caplog.text


def test_persist_migrates_lowercase_legacy_render_path(tmp_path):
    _brief(tmp_path, "---\nrender_path: t2v\nworkflow: x\n---\n", name="brief.md")

    assert rp.persist(tmp_path, "html_launch") is True

    text = (tmp_path / "brief.md").read_text(encoding="utf-8")
    assert "production_profile: html_launch" in text
    assert "render_path:" not in text
    assert rp.resolve(tmp_path) == ("html_launch", "brief.md:production_profile")


def test_lowercase_legacy_render_path_reports_its_real_source(tmp_path):
    _brief(tmp_path, "---\nrender_path: t2v\n---\n", name="brief.md")

    assert rp.resolve(tmp_path) == ("t2v_brand_film", "brief.md:render_path")


def test_invalid_profile_warns_and_stays_unset(tmp_path, caplog):
    _brief(tmp_path, "---\nproduction_profile: veo\n---\n")
    with caplog.at_level(logging.WARNING, logger="clip_weave.core.render_path"):
        assert rp.resolve(tmp_path) == (None, "unset")
    assert "veo" in caplog.text


def test_default_is_html_launch():
    assert rp.DEFAULT == "html_launch"
    assert rp.PROFILES == ("html_launch", "t2v_brand_film")


def test_engine_maps_each_profile_to_one_pipeline():
    assert rp.engine("html_launch") == "html"
    assert rp.engine("t2v_brand_film") == "t2v"


def test_persist_returns_false_without_a_brief(tmp_path):
    assert rp.persist(tmp_path, "t2v_brand_film") is False


def test_persist_then_resolve_round_trips(tmp_path):
    _brief(tmp_path, "---\nworkflow: x\n---\n\n## Intent\n体验\n")
    assert rp.persist(tmp_path, "t2v_brand_film") is True
    assert rp.resolve(tmp_path)[0] == "t2v_brand_film"


def test_persist_migrates_legacy_render_to_one_profile_key(tmp_path):
    _brief(tmp_path, "---\nrender: t2v\nworkflow: x\n---\n")
    assert rp.persist(tmp_path, "html_launch") is True
    text = (tmp_path / "BRIEF.md").read_text(encoding="utf-8")
    assert "production_profile: html_launch" in text
    assert "render:" not in text
    assert rp.resolve(tmp_path)[0] == "html_launch"


def test_persist_preserves_the_rest_of_the_brief(tmp_path):
    _brief(tmp_path, "---\nworkflow: product-launch-video\n---\n\n## Intent\n核心信息\n")
    rp.persist(tmp_path, "html_launch")
    text = (tmp_path / "BRIEF.md").read_text()
    assert "workflow: product-launch-video" in text
    assert "核心信息" in text


def test_persist_creates_frontmatter_when_there_is_none(tmp_path):
    _brief(tmp_path, "# Just a heading\n\nsome prose\n")
    assert rp.persist(tmp_path, "t2v_brand_film") is True
    text = (tmp_path / "BRIEF.md").read_text()
    assert text.startswith("---\nproduction_profile: t2v_brand_film\n---\n")
    assert "some prose" in text


def test_frame_level_render_directive_is_rejected():
    with pytest.raises(rp.ProfileError, match="frame-level render"):
        rp.validate_frames([{"render": "html"}])


def test_frame_level_render_path_alias_is_rejected():
    with pytest.raises(rp.ProfileError, match="frame-level render"):
        rp.validate_frames([{}, {"render_path": "t2v"}])


@pytest.mark.parametrize("key", ["Render", "Render_Path"])
def test_frame_level_renderer_directive_is_rejected_case_insensitively(key):
    with pytest.raises(rp.ProfileError, match="frame-level render"):
        rp.validate_frames([{key: "t2v"}])


def test_frames_without_renderer_directives_are_valid():
    rp.validate_frames([{}, {"scene": "night driving"}])
