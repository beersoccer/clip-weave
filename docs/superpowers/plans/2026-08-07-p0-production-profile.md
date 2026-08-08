# P0 Production Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every Clip Weave project choose one canonical Production Profile (`html_launch` or `t2v_brand_film`), remove frame-level renderer routing, and prevent an HTML project from submitting video-generation tasks.

**Architecture:** `core/render_path.py` becomes the one profile contract: it owns the persisted `production_profile` frontmatter field, maps a profile to its engine, migrates legacy project-level `render` values on write, and rejects frame-level `render` metadata. The CLI chooses and persists one profile at project creation; `gen-video` accepts only `t2v_brand_film`; `generate_clips()` no longer filters the storyboard by a frame-level renderer.

**Tech Stack:** Python 3.11, Click, pytest, existing `STORYBOARD.md` parser.

---

## File structure

- Modify: `src/clip_weave/core/render_path.py` — canonical profile schema, legacy migration, and frame-override validation.
- Modify: `src/clip_weave/core/video_pipeline.py` — remove the `render_default` filtering argument; reject forbidden per-frame overrides.
- Modify: `src/clip_weave/__main__.py` — replace `--render` with `--profile`; make `gen-video` fail before prompt creation outside `t2v_brand_film`.
- Modify: `tests/test_render_path.py` — profile resolution, persistence, migration and validation tests.
- Modify: `tests/test_video_pipeline.py` — replace mixed-routing tests with rejection and all-shots T2V tests.
- Modify: `tests/test_cli.py` — profile selection and HTML-project generation rejection tests.
- Modify: `README.md` and `docs/architecture.md` — describe the implemented project-level boundary, not the later P1–P5 target.

### Task 1: Define the canonical profile contract

**Files:**
- Modify: `tests/test_render_path.py`
- Modify: `src/clip_weave/core/render_path.py`

- [x] **Step 1: Write failing tests for profile resolution and legacy migration**

```python
def test_profile_resolves_from_canonical_frontmatter(tmp_path):
    _brief(tmp_path, "---\nproduction_profile: t2v_brand_film\n---\n")
    assert rp.resolve(tmp_path) == ("t2v_brand_film", "BRIEF.md:production_profile")


def test_persist_migrates_legacy_render_to_one_profile_key(tmp_path):
    _brief(tmp_path, "---\nrender: t2v\nworkflow: x\n---\n")
    assert rp.persist(tmp_path, "html_launch") is True
    text = (tmp_path / "BRIEF.md").read_text(encoding="utf-8")
    assert "production_profile: html_launch" in text
    assert "render:" not in text
    assert rp.resolve(tmp_path)[0] == "html_launch"


def test_engine_maps_each_profile_to_one_pipeline():
    assert rp.engine("html_launch") == "html"
    assert rp.engine("t2v_brand_film") == "t2v"
```

- [x] **Step 2: Run the focused test file and verify RED**

Run: `uv run pytest -q tests/test_render_path.py`

Expected: FAIL because `production_profile` is not recognised and `engine()` does not exist.

- [x] **Step 3: Implement the minimal canonical profile contract**

Replace the render-path literals with:

```python
ProductionProfile = Literal["html_launch", "t2v_brand_film"]
Engine = Literal["html", "t2v"]
PROFILES: tuple[ProductionProfile, ...] = ("html_launch", "t2v_brand_film")
DEFAULT: ProductionProfile = "html_launch"
_PROFILE_LINE = re.compile(r"^production_profile\s*:\s*(\S+)\s*$", re.MULTILINE | re.IGNORECASE)
_LEGACY_RENDER_LINE = re.compile(r"^(render|render_path)\s*:\s*(\S+)\s*$", re.MULTILINE | re.IGNORECASE)
_LEGACY_TO_PROFILE = {"html": "html_launch", "t2v": "t2v_brand_film"}
_ENGINE_BY_PROFILE = {"html_launch": "html", "t2v_brand_film": "t2v"}


def engine(profile: ProductionProfile) -> Engine:
    return _ENGINE_BY_PROFILE[profile]
```

`resolve()` reads `production_profile` first, then maps a legacy project-level `render`/`render_path` value for read compatibility and logs a migration warning. `persist()` removes all legacy render lines from frontmatter, writes exactly one `production_profile:` line, and preserves the rest of the brief.

- [x] **Step 4: Run the focused test file and verify GREEN**

Run: `uv run pytest -q tests/test_render_path.py`

Expected: PASS.

### Task 2: Make frame-level renderer directives invalid

**Files:**
- Modify: `tests/test_render_path.py`
- Modify: `tests/test_video_pipeline.py`
- Modify: `src/clip_weave/core/render_path.py`
- Modify: `src/clip_weave/core/video_pipeline.py`

- [x] **Step 1: Write failing tests for forbidden frame metadata and all-shot T2V selection**

```python
def test_frame_level_render_directive_is_rejected():
    with pytest.raises(rp.ProfileError, match="frame-level render"):
        rp.validate_frames([{"render": "html"}])


def test_t2v_pipeline_rejects_mixed_storyboard(tmp_path):
    with pytest.raises(VideoGenError, match="frame-level render"):
        _run(tmp_path, MIXED_STORYBOARD, model=FakeModel())


def test_t2v_pipeline_generates_every_unannotated_storyboard_frame(tmp_path):
    results = _run(tmp_path, STORYBOARD, model=FakeModel())
    assert [result.index for result in results] == [1, 2]
```

- [x] **Step 2: Run the focused tests and verify RED**

Run: `uv run pytest -q tests/test_render_path.py tests/test_video_pipeline.py`

Expected: FAIL because frame directives are still interpreted as routing overrides.

- [x] **Step 3: Implement frame validation and remove the filtering API**

Add `ProfileError(ValueError)` and `validate_frames(frame_meta: Iterable[Mapping[str, str]]) -> None` to `render_path.py`. It raises when any frame contains `render` or `render_path`, listing one-based frame positions. In `generate_clips()`, remove the `render_default` parameter and `frame_path` import, call `validate_frames([frame.meta for frame in sb.frames])` after parsing, and translate `ProfileError` to `VideoGenError` with the same actionable message. Keep `--frames` as a partial rerun selector; it is not a renderer override.

- [x] **Step 4: Run the focused tests and verify GREEN**

Run: `uv run pytest -q tests/test_render_path.py tests/test_video_pipeline.py`

Expected: PASS.

### Task 3: Enforce the production profile in the CLI

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `src/clip_weave/__main__.py`

- [x] **Step 1: Write failing CLI tests**

```python
def test_run_persists_explicit_production_profile(tmp_path):
    runner = CliRunner()
    with patch("clip_weave.__main__.pipeline_run", return_value=tmp_path):
        result = runner.invoke(cli, ["run", "--message", "品牌片", "--profile", "t2v_brand_film"])
    assert result.exit_code == 0, result.output
    assert "production_profile: t2v_brand_film" in (tmp_path / "BRIEF.md").read_text()


def test_gen_video_rejects_html_profile_before_creating_prompts(tmp_path):
    storyboard = _write_storyboard_and_html_profile(tmp_path)
    runner = CliRunner()
    with patch("clip_weave.core.t2v_prompt.load_or_create") as create_prompts:
        result = runner.invoke(cli, ["gen-video", str(storyboard), "--provider", "doubao"])
    assert result.exit_code == 2
    assert "html_launch" in result.output
    create_prompts.assert_not_called()
```

- [x] **Step 2: Run the focused CLI tests and verify RED**

Run: `uv run pytest -q tests/test_cli.py`

Expected: FAIL because `--profile` is not a CLI option and HTML projects can bypass the old warning.

- [x] **Step 3: Implement profile-only CLI behavior**

Change `run` to expose `--profile html_launch|t2v_brand_film|ask` and rename `_settle_render_path()` to `_settle_production_profile()`. Its prompt explains the two product outcomes without mentioning per-frame mixing. On non-interactive runs it persists `html_launch`.

At the start of `gen_video_cmd()`, resolve the profile. If missing, raise `click.UsageError` explaining that the project must first select `t2v_brand_film`; if `engine(profile) != "t2v"`, raise `click.UsageError` before `load_or_create()`. Remove the old `--yes` HTML bypass and stop passing `render_default` to `generate_clips()`.

- [x] **Step 4: Run the focused CLI tests and verify GREEN**

Run: `uv run pytest -q tests/test_cli.py`

Expected: PASS.

### Task 4: Synchronize public documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/architecture.md`

- [x] **Step 1: Update README examples and capability wording**

Replace `--render html` with `--profile html_launch`. State that each project has one profile; `html_launch` uses HyperFrames and `t2v_brand_film` is the current video-generation route. Remove all instructions to write frame-level `render:` values. Keep T2I→I2V and five quality gates described only as planned in `production-quality-loop.md`.

- [x] **Step 2: Update the architecture render-path section**

Document canonical `production_profile`, the legacy read migration, the `html_launch`/`t2v_brand_film` mapping, the rejection of frame-level renderer fields, and the fact that current `t2v_brand_film` generation remains the pre-P3 T2V implementation until its keyframe pipeline lands.

- [x] **Step 3: Verify documentation has no obsolete routing claims**

Run: `rg -n -i 'per-frame|逐帧.*render|frame-level.*render|STORYBOARD.*render:|--render|mixed' README.md docs/architecture.md`

Expected: no matches.

### Task 5: Final regression and review

**Files:**
- Review: `src/clip_weave/core/render_path.py`
- Review: `src/clip_weave/core/video_pipeline.py`
- Review: `src/clip_weave/__main__.py`
- Review: `tests/test_render_path.py`
- Review: `tests/test_video_pipeline.py`
- Review: `tests/test_cli.py`
- Review: `README.md`
- Review: `docs/architecture.md`

- [x] **Step 1: Run the changed-scope regression suite**

Run: `uv run pytest -q tests/test_render_path.py tests/test_video_pipeline.py tests/test_cli.py`

Expected: PASS.

- [x] **Step 2: Run the full offline suite and CLI smoke test**

Run: `uv run pytest -q && uv run python -m clip_weave --help`

Expected: all tests pass and help lists `run`, `gen-video`, `guard`, `match-assets`, and `route`.

- [x] **Step 3: Check the final diff**

Run: `git diff --check && git diff -- src/clip_weave/core/render_path.py src/clip_weave/core/video_pipeline.py src/clip_weave/__main__.py tests/test_render_path.py tests/test_video_pipeline.py tests/test_cli.py README.md docs/architecture.md`

Expected: no whitespace errors; every change implements the P0 boundary and no P1–P5 behavior is implied as complete.

### Review follow-up: close discovered P0 boundary gaps

- [x] Persist the selected profile before profile-specific delegation, including the resume path.
- [x] Accept YAML inline comments in canonical/legacy profile frontmatter and migrate supported legacy files in place.
- [x] Reject case-insensitive frame-level renderer keys in `gen-video` and in the `guard` preflight when a storyboard exists.
- [x] Make the BRIEF template, active skill guidance, delegation prompt, README, and resume paths branch on `production_profile`.
- [x] Add regression coverage for the above and re-run focused, full, CLI-smoke, and diff checks.
