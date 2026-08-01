"""Tests for the project-level render-path decision.

The path is the user's choice, made once per project in BRIEF.md rather than
inferred per frame. `visual_type` stays available as a per-frame override, which
only matters for a `mixed` project.
"""

import logging

import pytest

from clip_weave.core import render_path as rp


def _brief(tmp_path, body: str, name: str = "BRIEF.md"):
    (tmp_path / name).write_text(body, encoding="utf-8")
    return tmp_path


# ── resolve ───────────────────────────────────────────────────────────────────

def test_unset_when_there_is_no_brief(tmp_path):
    assert rp.resolve(tmp_path) == (None, "unset")


def test_unset_when_brief_has_no_render_key(tmp_path):
    _brief(tmp_path, "---\nworkflow: product-launch-video\n---\n\n## Intent\n")
    assert rp.resolve(tmp_path) == (None, "unset")


@pytest.mark.parametrize("value", ["html", "t2v", "mixed"])
def test_every_valid_value_resolves(tmp_path, value):
    _brief(tmp_path, f"---\nworkflow: x\nrender: {value}\n---\n")
    path, source = rp.resolve(tmp_path)
    assert path == value
    assert source == "BRIEF.md:render"


def test_render_path_alias_is_accepted(tmp_path):
    _brief(tmp_path, "---\nrender_path: t2v\n---\n")
    path, source = rp.resolve(tmp_path)
    assert path == "t2v"
    assert source == "BRIEF.md:render_path"


def test_value_is_case_insensitive_and_dequoted(tmp_path):
    _brief(tmp_path, '---\nrender: "T2V"\n---\n')
    assert rp.resolve(tmp_path)[0] == "t2v"


def test_lowercase_brief_filename_is_read(tmp_path):
    """`resolve()` tries "BRIEF.md" then "brief.md" — both must be readable.

    On a case-insensitive filesystem (macOS default) the two names collide, so
    this only proves the lowercase branch exists, not that it is reached first.
    `test_persist_ignores_a_lowercase_brief` below exercises the same branch from
    the write side, where the collision does not mask anything.
    """
    _brief(tmp_path, "---\nrender: mixed\n---\n", name="brief.md")
    path, source = rp.resolve(tmp_path)
    assert path == "mixed"
    assert source in ("BRIEF.md:render", "brief.md:render")


def test_invalid_value_warns_and_stays_unset(tmp_path, caplog):
    _brief(tmp_path, "---\nrender: veo\n---\n")
    with caplog.at_level(logging.WARNING, logger="clip_weave.core.render_path"):
        path, source = rp.resolve(tmp_path)
    assert path is None
    assert source == "unset"
    assert "veo" in caplog.text


def test_render_outside_frontmatter_is_ignored(tmp_path):
    """Only the frontmatter block counts — prose must not set the render path."""
    _brief(tmp_path, "---\nworkflow: x\n---\n\n## Notes\nrender: t2v\n")
    assert rp.resolve(tmp_path) == (None, "unset")


def test_default_is_html():
    assert rp.DEFAULT == "html"
    assert rp.VALID == ("html", "t2v", "mixed")


# ── persist ───────────────────────────────────────────────────────────────────

def test_persist_returns_false_without_a_brief(tmp_path):
    assert rp.persist(tmp_path, "t2v") is False


def test_persist_then_resolve_round_trips(tmp_path):
    _brief(tmp_path, "---\nworkflow: x\n---\n\n## Intent\n体验\n")
    assert rp.persist(tmp_path, "t2v") is True
    assert rp.resolve(tmp_path)[0] == "t2v"


def test_persist_overwrites_an_existing_value(tmp_path):
    _brief(tmp_path, "---\nrender: html\nworkflow: x\n---\n")
    rp.persist(tmp_path, "mixed")
    assert rp.resolve(tmp_path)[0] == "mixed"
    # exactly one render: line survives — no duplicate keys in the frontmatter
    assert (tmp_path / "BRIEF.md").read_text().count("render:") == 1


def test_persist_preserves_the_rest_of_the_brief(tmp_path):
    _brief(tmp_path, "---\nworkflow: product-launch-video\n---\n\n## Intent\n核心信息\n")
    rp.persist(tmp_path, "t2v")
    text = (tmp_path / "BRIEF.md").read_text()
    assert "workflow: product-launch-video" in text
    assert "核心信息" in text


def test_persist_creates_frontmatter_when_there_is_none(tmp_path):
    _brief(tmp_path, "# Just a heading\n\nsome prose\n")
    assert rp.persist(tmp_path, "t2v") is True
    text = (tmp_path / "BRIEF.md").read_text()
    assert text.startswith("---\nrender: t2v\n---\n")
    assert "some prose" in text
    assert rp.resolve(tmp_path)[0] == "t2v"


def test_persist_writes_only_the_brief_md_path(tmp_path):
    """persist() checks Path(project_dir) / "BRIEF.md" — it never looks for brief.md.

    On a case-insensitive filesystem this check also matches an existing
    lowercase brief.md, so this pins the code path (`BRIEF.md` is what gets
    opened), not a case-sensitivity guarantee.
    """
    _brief(tmp_path, "---\nworkflow: x\n---\n")
    assert rp.persist(tmp_path, "t2v") is True
    assert (tmp_path / "BRIEF.md").read_text().count("render:") == 1


# ── frame_path ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", ["motion", "html", "graphic", "graphics"])
def test_frame_html_vocabulary(value):
    assert rp.frame_path({"visual_type": value}, "t2v") == "html"


@pytest.mark.parametrize(
    "value", ["live_action", "live-action", "t2v", "footage", "realistic"]
)
def test_frame_t2v_vocabulary(value):
    assert rp.frame_path({"visual_type": value}, "html") == "t2v"


def test_frame_value_is_case_insensitive():
    assert rp.frame_path({"visual_type": "Live-Action"}, "html") == "t2v"


def test_visualtype_without_underscore_is_accepted():
    assert rp.frame_path({"visualtype": "live_action"}, "html") == "t2v"


@pytest.mark.parametrize(
    "project_default,expected", [("html", "html"), ("t2v", "t2v"), ("mixed", "html")]
)
def test_unannotated_frame_follows_the_project_default(project_default, expected):
    """A `mixed` project with an unannotated frame falls to HTML — the free path."""
    assert rp.frame_path({}, project_default) == expected


def test_unrecognised_frame_value_falls_back_to_the_project_default(caplog):
    """A typo must never be read as "generate this"."""
    assert rp.frame_path({"visual_type": "nonsense"}, "t2v") == "t2v"
    assert rp.frame_path({"visual_type": "nonsense"}, "html") == "html"
    assert rp.frame_path({"visual_type": "nonsense"}, "mixed") == "html"
