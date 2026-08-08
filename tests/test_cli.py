"""Tests for the v6.0 CLI: run, guard, match-assets."""

from pathlib import Path
from unittest.mock import patch
from click.testing import CliRunner
from clip_weave.__main__ import cli


def _storyboard_and_profile(tmp_path, profile: str):
    (tmp_path / "BRIEF.md").write_text(
        f"---\nproduction_profile: {profile}\n---\n", encoding="utf-8"
    )
    storyboard = tmp_path / "STORYBOARD.md"
    storyboard.write_text(
        "---\nformat: 1920x1080\n---\n\n## Frame 1\n- scene: x\n- duration: 5s\n",
        encoding="utf-8",
    )
    return storyboard


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


def test_run_passes_explicit_production_profile_to_pipeline(tmp_path):
    runner = CliRunner()
    with patch("clip_weave.__main__.pipeline_run", return_value=tmp_path) as pipeline:
        result = runner.invoke(
            cli,
            ["run", "--message", "品牌片", "--profile", "t2v_brand_film"],
        )

    assert result.exit_code == 0, result.output
    assert pipeline.call_args.kwargs["production_profile"] == "t2v_brand_film"


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


def test_guard_rejects_storyboard_frame_level_renderer_directives(tmp_path):
    comp_dir = tmp_path / "compositions"
    comp_dir.mkdir()
    (tmp_path / "STORYBOARD.md").write_text(
        "---\nformat: 1920x1080\n---\n\n## Frame 1\n- scene: x\n- Render: t2v\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(cli, ["guard", str(tmp_path)])

    assert result.exit_code == 2
    assert "frame-level render" in result.output


def test_gen_video_rejects_html_profile_before_creating_prompts(tmp_path):
    storyboard = _storyboard_and_profile(tmp_path, "html_launch")
    runner = CliRunner()

    with patch("clip_weave.core.t2v_prompt.load_or_create") as create_prompts:
        result = runner.invoke(cli, ["gen-video", str(storyboard), "--provider", "doubao"])

    assert result.exit_code == 2
    assert "html_launch" in result.output
    create_prompts.assert_not_called()


def test_gen_video_needs_review_does_not_suggest_removed_frame_routing(tmp_path):
    """A t2v project must revise its prompts or profile as a whole, never route
    an individual flagged frame through the removed HTML/T2V mixing path."""
    storyboard = _storyboard_and_profile(tmp_path, "t2v_brand_film")

    class FakeSpec:
        index = 1
        needs_review = True
        notes = ""

    class FakeDoc:
        specs = [FakeSpec()]

    runner = CliRunner()
    with patch(
        "clip_weave.core.t2v_prompt.load_or_create",
        return_value=(FakeDoc(), tmp_path / "T2V-PROMPTS.md", True),
    ):
        result = runner.invoke(
            cli, ["gen-video", str(storyboard), "--provider", "doubao", "--prompts-only"]
        )

    assert result.exit_code == 0, result.output
    assert "修订提示词，或重新选择整个项目的 Production Profile" in result.output
    assert "留在 HTML 路径" not in result.output


def test_gen_video_warns_when_style_flag_will_be_ignored(tmp_path):
    """--style is silently ineffective once T2V-PROMPTS.md already exists and
    --regenerate-prompts was not passed — the operator must be told, not left
    to wonder why the flag had no effect."""
    storyboard = _storyboard_and_profile(tmp_path, "t2v_brand_film")

    class FakeSpec:
        index = 1
        needs_review = False
        notes = ""

    class FakeDoc:
        specs = [FakeSpec()]

    runner = CliRunner()
    with patch(
        "clip_weave.core.t2v_prompt.load_or_create",
        return_value=(FakeDoc(), tmp_path / "T2V-PROMPTS.md", False),  # created=False
    ), patch("clip_weave.core.t2v_prompt.literal_prompt", return_value="p"):
        result = runner.invoke(
            cli,
            ["gen-video", str(storyboard), "--provider", "doubao", "--style", "35mm film",
             "--dry-run"],
        )

    assert "--style" in result.output
    assert "T2V-PROMPTS.md" in result.output


def test_gen_video_no_warning_when_prompts_file_is_freshly_created(tmp_path):
    """The warning must only fire when the flag is actually being ignored —
    a fresh file means build_doc() DID see the flag, so no warning is needed."""
    storyboard = _storyboard_and_profile(tmp_path, "t2v_brand_film")

    class FakeSpec:
        index = 1
        needs_review = False
        notes = ""

    class FakeDoc:
        specs = [FakeSpec()]

    runner = CliRunner()
    with patch(
        "clip_weave.core.t2v_prompt.load_or_create",
        return_value=(FakeDoc(), tmp_path / "T2V-PROMPTS.md", True),  # created=True
    ), patch("clip_weave.core.t2v_prompt.literal_prompt", return_value="p"):
        result = runner.invoke(
            cli,
            ["gen-video", str(storyboard), "--provider", "doubao", "--style", "35mm film",
             "--dry-run"],
        )

    assert "--style" not in result.output


def test_gen_video_no_warning_when_no_relevant_flags_passed(tmp_path):
    """No style/voiceover/audio flags passed at all → nothing to warn about,
    even if the prompts file already existed."""
    storyboard = _storyboard_and_profile(tmp_path, "t2v_brand_film")

    class FakeSpec:
        index = 1
        needs_review = False
        notes = ""

    class FakeDoc:
        specs = [FakeSpec()]

    runner = CliRunner()
    with patch(
        "clip_weave.core.t2v_prompt.load_or_create",
        return_value=(FakeDoc(), tmp_path / "T2V-PROMPTS.md", False),
    ), patch("clip_weave.core.t2v_prompt.literal_prompt", return_value="p"):
        result = runner.invoke(
            cli, ["gen-video", str(storyboard), "--provider", "doubao", "--dry-run"]
        )

    assert "--style" not in result.output
    assert "--include-voiceover" not in result.output
    assert "--generate-audio" not in result.output
