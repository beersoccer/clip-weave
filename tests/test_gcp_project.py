"""Tests for GCP project resolution.

Vertex needs a real Google Cloud project id in its resource path — it is the
billing identity, not a label, so an invented name returns 403 CONSUMER_INVALID.
These tests pin the resolution order so the id only has to be set once.
"""

import pytest

from clip_weave.adapters.video_gen import gcp_project
from clip_weave.adapters.video_gen.gcp_project import looks_like_project_id, resolve_project

_ENV_VARS = ("VERTEX_VIDEO_PROJECT", "GOOGLE_CLOUD_PROJECT", "GCLOUD_PROJECT")


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """No env leakage, and gcloud is never invoked unless a test opts in."""
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(gcp_project, "_from_gcloud", lambda: None)


@pytest.mark.parametrize("var", _ENV_VARS)
def test_env_vars_are_honoured(monkeypatch, var):
    monkeypatch.setenv(var, "env-project")
    project, source = resolve_project()
    assert project == "env-project"
    assert source == f"env {var}"


def test_vertex_var_wins_over_google_cloud_project(monkeypatch):
    monkeypatch.setenv("VERTEX_VIDEO_PROJECT", "vertex-one")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "google-one")
    assert resolve_project()[0] == "vertex-one"


def test_env_wins_over_frontmatter(monkeypatch, tmp_path):
    monkeypatch.setenv("VERTEX_VIDEO_PROJECT", "from-env")
    sb = tmp_path / "STORYBOARD.md"
    sb.write_text("---\nvertex_project: from-file\n---\n", encoding="utf-8")
    assert resolve_project(sb)[0] == "from-env"


@pytest.mark.parametrize(
    "key", ["vertex_project", "gcp_project", "google_cloud_project", "project_id"]
)
def test_storyboard_frontmatter_keys(tmp_path, key):
    sb = tmp_path / "STORYBOARD.md"
    sb.write_text(f"---\nformat: 1920x1080\n{key}: sb-proj\n---\n\n## Frame 1\n", encoding="utf-8")
    project, source = resolve_project(sb)
    assert project == "sb-proj"
    assert source == f"STORYBOARD.md:{key}"


def test_falls_back_to_sibling_brief(tmp_path):
    sb = tmp_path / "STORYBOARD.md"
    sb.write_text("---\nformat: 1920x1080\n---\n", encoding="utf-8")
    (tmp_path / "BRIEF.md").write_text("---\nvertex_project: brief-proj\n---\n", encoding="utf-8")
    project, source = resolve_project(sb)
    assert project == "brief-proj"
    assert source == "BRIEF.md:vertex_project"


def test_quotes_are_stripped(tmp_path):
    sb = tmp_path / "STORYBOARD.md"
    sb.write_text('---\nvertex_project: "quoted-proj"\n---\n', encoding="utf-8")
    assert resolve_project(sb)[0] == "quoted-proj"


def test_only_the_frontmatter_block_is_scanned(tmp_path):
    sb = tmp_path / "STORYBOARD.md"
    sb.write_text(
        "---\nformat: 1920x1080\n---\n\n## Frame 1\nvertex_project: body-not-frontmatter\n",
        encoding="utf-8",
    )
    assert resolve_project(sb)[0] is None


def test_gcloud_is_the_last_resort(monkeypatch, tmp_path):
    monkeypatch.setattr(gcp_project, "_from_gcloud", lambda: "gcloud-proj")
    project, source = resolve_project(tmp_path / "STORYBOARD.md")
    assert project == "gcloud-proj"
    assert source == "gcloud config"


def test_unresolved_when_nothing_is_configured(tmp_path):
    assert resolve_project(tmp_path / "missing.md") == (None, "unresolved")


def test_missing_storyboard_file_is_not_an_error(tmp_path):
    assert resolve_project(tmp_path / "nope" / "STORYBOARD.md")[0] is None


@pytest.mark.parametrize("value", ["my-project", "abc123", "a-very-long-but-valid-proj-id"])
def test_valid_project_ids(value):
    assert looks_like_project_id(value) is True


@pytest.mark.parametrize(
    "value",
    [
        "abc",              # too short (< 6)
        "1project",         # must start with a letter
        "My-Project",       # uppercase not allowed
        "proj_underscore",  # underscore not allowed
        "trailing-",        # must end alphanumeric
        "小米-su7",          # non-ascii
        "",
    ],
)
def test_invalid_project_ids(value):
    assert looks_like_project_id(value) is False
