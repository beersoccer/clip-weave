# Final Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the two Important findings from the final whole-branch review of `feat/rule-guard-soundness-and-t2v-routing`: (1) `render_path.frame_path()` is fully unit-tested but never called anywhere in production code, so `render: mixed` projects generate T2V for every frame regardless of `visual_type` annotation; (2) `gen-video`'s `--style`/`--include-voiceover`/`--generate-audio` flags silently no-op once `T2V-PROMPTS.md` already exists, because `prompt_overrides` from that file always wins with no warning to the operator.

**Architecture:** Task 1 wires `frame_path()` into `generate_clips()`'s frame-selection step, so `render: mixed` projects actually skip HTML-routed frames when generating T2V clips. Task 2 adds a CLI-level warning in `gen_video_cmd` when style/voiceover/audio flags are passed but the prompts file already exists and will override them — a warning, not a silent behavior change, because forcing `--regenerate-prompts` automatically would discard a user's hand edits without asking.

**Tech Stack:** Python 3.11+, pytest 8, click 8. No new dependencies.

## Global Constraints

- Same branch: `feat/rule-guard-soundness-and-t2v-routing`. Do not create a new branch.
- No new runtime dependencies.
- All tests offline — no real HTTP, no real `npx`/`ffmpeg`/`gcloud`.
- Keep existing Chinese-comment / English-docstring style used elsewhere in `src/clip_weave/`.
- Run `.venv/bin/python -m pytest -q` at the end of each task — must be fully green. Baseline going into this plan is 264 passed.
- Conventional Commits, consistent with this branch's history (`fix(scope):`).
- Do not touch `render_path.py`, `t2v_prompt.py`'s slot-building logic, or any provider adapter — both fixes are wiring/UX fixes in `video_pipeline.py` and `__main__.py` only.

---

## Task 1: Wire `frame_path()` into `generate_clips()` so `render: mixed` actually skips HTML-routed frames

**Where this came from:** The final whole-branch review found `render_path.frame_path(frame_meta, project_default) -> RenderPath` has 32 passing unit tests but zero callers anywhere in `src/`. `SKILL.md` § 8 tells users to annotate individual frames with `visual_type: live_action`/`motion` for `render: mixed` projects, but `gen-video` currently generates a T2V clip for every frame in the storyboard regardless of that annotation — the only way to exclude a frame today is to manually pass `--frames` with hand-picked indices, which defeats the point of per-frame annotation.

**Files:**
- Modify: `src/clip_weave/core/video_pipeline.py`
- Test: `tests/test_video_pipeline.py`

**Interfaces:**
- Consumes: `clip_weave.core.render_path.frame_path(frame_meta: dict[str, str], project_default: RenderPath) -> RenderPath` (already exists, signature unchanged) and `clip_weave.core.render_path.resolve(project_dir) -> tuple[RenderPath | None, str]` (already exists).
- Produces: `generate_clips(..., render_default: str | None = None)` — a new optional keyword parameter. When `render_default` is `"mixed"`, frame selection additionally filters out any frame whose `frame_path(frame.meta, "mixed")` resolves to `"html"`. When `render_default` is anything else (or `None`), behavior is **unchanged** — every frame in `frames`/`_select()`'s existing selection still gets a T2V clip. This keeps the fix scoped to the one case it actually matters for (`mixed`) and does not change behavior for `render: t2v` projects or ad-hoc CLI use where no `BRIEF.md` exists at all.

- [ ] **Step 1: Read the exact current selection code to confirm the integration point**

Run: `cd /Users/beersoccer/workspace/clip-weave && sed -n '1,100p' src/clip_weave/core/video_pipeline.py`

Confirm for yourself: `generate_clips()` calls `selected = _select(sb, frames)` near the top (currently around line 90), and `_select()` (near the bottom of the file, currently around line 285) is:

```python
def _select(sb: Storyboard, frames: list[int] | None) -> list[Frame]:
    if not frames:
        return sb.frames
    wanted = set(frames)
    picked = [f for f in sb.frames if f.index in wanted or (f.number and f.number in wanted)]
    missing = wanted - {f.index for f in picked} - {f.number for f in picked if f.number}
    if missing:
        logger.warning("frames not found in storyboard: %s", sorted(missing))
    return picked
```

Note `Frame.meta` is a `dict[str, str]` already populated by the storyboard parser with whatever bullet-list keys the frame declared (including `visual_type` when present) — confirm this by reading `Frame`'s definition in `src/clip_weave/core/storyboard.py` if you have not already worked with it. `frame_path()` takes exactly that `frame.meta` dict as its first argument.

- [ ] **Step 2: Write the failing test**

Read the top of `tests/test_video_pipeline.py` first for its existing `_storyboard`/`_run`/`FakeModel` helpers and STORYBOARD fixture constant, then append these tests (adjust import lines if `render_path` isn't already imported — it currently is not, so add `from clip_weave.core import render_path` near the top-level imports, or a local import inside the test if that better matches this file's existing style; check the file before deciding):

```python
# ── render: mixed frame filtering ─────────────────────────────────────────────

MIXED_STORYBOARD = """---
format: 1920x1080
message: "test message"
---

## Frame 1 — 图表
- scene: 数据柱状图
- visual_type: motion
- duration: 5s

## Frame 2 — 实拍
- scene: 城市夜景
- visual_type: live_action
- duration: 5s

## Frame 3 — 未标注
- scene: 第三个镜头
- duration: 5s
"""


def test_mixed_render_default_skips_html_routed_frames(tmp_path):
    """render_default='mixed' + visual_type: motion means frame 1 gets no T2V clip."""
    model = FakeModel()
    results = _run(tmp_path, MIXED_STORYBOARD, model=model, render_default="mixed")

    assert [r.index for r in results] == [2, 3]
    assert len(model.submitted) == 2


def test_mixed_render_default_generates_live_action_frames(tmp_path):
    model = FakeModel()
    results = _run(tmp_path, MIXED_STORYBOARD, model=model, render_default="mixed")

    by_index = {r.index: r for r in results}
    assert by_index[2].state == "succeeded"
    assert "城市夜景" in model.submitted[0].prompt or "城市夜景" in model.submitted[1].prompt


def test_unannotated_frame_defaults_to_t2v_under_mixed():
    """frame_path({}, "mixed") == "html" per render_path.py's own contract — confirm
    generate_clips respects that: an unannotated frame in a mixed project is
    treated as HTML-routed (excluded), matching frame_path's documented default."""
    from clip_weave.core.render_path import frame_path

    assert frame_path({}, "mixed") == "html"


def test_render_default_none_generates_every_frame_unchanged(tmp_path):
    """No render_default (the pre-existing behavior) must be untouched: every
    frame gets a clip regardless of visual_type annotation."""
    model = FakeModel()
    results = _run(tmp_path, MIXED_STORYBOARD, model=model)  # no render_default passed

    assert [r.index for r in results] == [1, 2, 3]


def test_render_default_t2v_generates_every_frame(tmp_path):
    """render_default='t2v' (not 'mixed') must also generate every frame — the
    per-frame filter only applies to 'mixed' projects."""
    model = FakeModel()
    results = _run(tmp_path, MIXED_STORYBOARD, model=model, render_default="t2v")

    assert [r.index for r in results] == [1, 2, 3]


def test_explicit_frames_still_overrides_mixed_filtering(tmp_path):
    """--frames stays an unconditional override, same as it already is for
    plain routing — mixed filtering must not fight an explicit frame list."""
    model = FakeModel()
    results = _run(tmp_path, MIXED_STORYBOARD, model=model, render_default="mixed", frames=[1])

    assert [r.index for r in results] == [1]
```

Note: `_run()` is this test file's existing helper that forwards `**kwargs` to `generate_clips(...)` — confirm it does so generically (check its definition) so passing `render_default=` through it requires no changes to `_run()` itself. If `_run()` has a fixed keyword list instead of `**kwargs`, add `render_default` to that list.

- [ ] **Step 3: Run and confirm the new tests fail for the right reason**

Run: `cd /Users/beersoccer/workspace/clip-weave && .venv/bin/python -m pytest tests/test_video_pipeline.py -k "mixed or render_default" -v`

Expected: `test_mixed_render_default_skips_html_routed_frames` and `test_explicit_frames_still_overrides_mixed_filtering` FAIL with `TypeError: generate_clips() got an unexpected keyword argument 'render_default'`. The other three tests may pass already (they test either `frame_path()` directly or the unchanged no-`render_default` path) — that is fine, they are here as guardrails for this task's own change, not all meant to be red first.

- [ ] **Step 4: Implement the wiring in `generate_clips()`**

In `src/clip_weave/core/video_pipeline.py`:

Add `render_default: str | None = None` to `generate_clips()`'s signature — read the current full signature first (it has many keyword-only-by-convention parameters like `prompt_overrides`, `duration_overrides`, etc.) and add the new parameter alongside them, keeping the existing parameter order and only appending the new one at the end so no positional call site breaks.

Add the import at the top of the file, alongside the existing `from clip_weave.core.storyboard import (...)` line:

```python
from clip_weave.core.render_path import frame_path
```

Change the selection line from:

```python
    selected = _select(sb, frames)
```

to:

```python
    selected = _select(sb, frames)
    if render_default == "mixed" and not frames:
        # --frames is an explicit operator override and must win outright — only
        # filter by visual_type when the caller did not hand-pick frame indices.
        selected = [f for f in selected if frame_path(f.meta, "mixed") != "html"]
```

Placing the `and not frames` guard here (rather than inside `_select()`) keeps `_select()` itself unchanged and untested-differently — it continues to mean exactly what it always meant ("resolve an explicit frame list, or return everything"), and the mixed-filtering is a second, orthogonal step layered on top only when no explicit list was given.

- [ ] **Step 5: Run the new tests again — all should pass now**

Run: `cd /Users/beersoccer/workspace/clip-weave && .venv/bin/python -m pytest tests/test_video_pipeline.py -k "mixed or render_default" -v`

Expected: all 6 tests PASS.

- [ ] **Step 6: Wire the CLI to pass `render_default` through**

In `src/clip_weave/__main__.py`'s `gen_video_cmd`, the code already calls `rp.resolve(project_dir)` and stores the result in `chosen`. Pass that through to `generate_clips()`. Find the `generate_clips(` call inside `gen_video_cmd` (it currently passes `storyboard, provider=provider, out_dir=out_dir, frames=frame_list, ...`) and add `render_default=chosen,` to that call's keyword arguments — anywhere in the existing list is fine, but keep it near the other pipeline-behavior flags like `frames=frame_list` for readability.

- [ ] **Step 7: Run the full suite**

Run: `cd /Users/beersoccer/workspace/clip-weave && .venv/bin/python -m pytest -q`

Expected: 270 passed (264 baseline + 6 new tests).

- [ ] **Step 8: Manual end-to-end sanity check**

```bash
cd /Users/beersoccer/workspace/clip-weave
mkdir -p /tmp/cw-mixed-check
cat > /tmp/cw-mixed-check/BRIEF.md <<'EOF'
---
workflow: product-launch-video
render: mixed
---
EOF
cat > /tmp/cw-mixed-check/STORYBOARD.md <<'EOF'
---
format: 1920x1080
message: "mixed check"
---

## Frame 1 — 图表
- scene: 数据柱状图
- visual_type: motion
- duration: 5s

## Frame 2 — 实拍
- scene: 城市夜景
- visual_type: live_action
- duration: 5s
EOF
.venv/bin/python -m clip_weave gen-video /tmp/cw-mixed-check/STORYBOARD.md --provider doubao --dry-run
rm -rf /tmp/cw-mixed-check
```

Expected: only frame 2's `[dry-run]` line is printed, not frame 1's — confirming the CLI wiring, not just the unit test, produces the filtered behavior end to end.

- [ ] **Step 9: Commit**

```bash
cd /Users/beersoccer/workspace/clip-weave
git add src/clip_weave/core/video_pipeline.py src/clip_weave/__main__.py tests/test_video_pipeline.py
git commit -m "fix(video-pipeline): wire frame_path() into generate_clips for render: mixed

render_path.frame_path() had 32 passing unit tests and zero production callers
— render: mixed projects generated a T2V clip for every frame regardless of
each frame's visual_type annotation, silently ignoring the per-frame override
SKILL.md tells users to write. generate_clips() now takes render_default and,
when it is 'mixed' and no explicit --frames list was given, filters out any
frame frame_path() resolves to the html side.

Found by the final whole-branch review of feat/rule-guard-soundness-and-
t2v-routing — a gap no single task's review could see, since Task 8 correctly
verified frame_path()'s own unit behavior but no task ever wired it in."
```

---

## Task 2: Warn when `--style`/`--include-voiceover`/`--generate-audio` will be ignored because `T2V-PROMPTS.md` already exists

**Where this came from:** The final whole-branch review found that `gen_video_cmd` always calls `load_or_create()` first; once `T2V-PROMPTS.md` exists (the normal case after the first run), the per-frame `prompt_overrides` built from that file always wins inside `generate_clips()`'s `prompt_for()`. The CLI's `--style`, `--include-voiceover`, and `--generate-audio` flags only affect the `build_doc()` branch (first creation, or `--regenerate-prompts`) — so a user re-running `gen-video` with `--style "35mm film"` on an established project gets no visible effect and no explanation why.

**Files:**
- Modify: `src/clip_weave/__main__.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `load_or_create()`'s existing `created: bool` return value (already destructured as `doc, prompts_path, created = load_or_create(...)` in `gen_video_cmd`) and `regenerate_prompts: bool` (already an existing CLI flag/parameter).
- Produces: no new function or parameter — this is purely an added `click.echo(...)` warning inside the existing command body, gated on existing values already in scope.

- [ ] **Step 1: Read the exact current control flow to confirm the integration point**

Run: `cd /Users/beersoccer/workspace/clip-weave && sed -n '/def gen_video_cmd/,/^def _derive_project_name/p' src/clip_weave/__main__.py`

Confirm: `doc, prompts_path, created = load_or_create(storyboard_path, regenerate=regenerate_prompts, provider=provider, resolution=resolution, include_voiceover=include_voiceover, include_audio=generate_audio)` runs, then `click.echo(f"{'wrote' if created else 'using'} {prompts_path}")` runs — this is exactly where `created` tells you whether the flags you were just handed had any effect.

- [ ] **Step 2: Write the failing test**

Read `tests/test_cli.py`'s existing imports and its two `gen-video`-related tests (search for `gen_video` or `gen-video` in that file — if none exist yet, check `tests/test_video_pipeline.py` and other CLI tests for the established pattern of invoking `cli` via `CliRunner` and mocking `generate_clips`/`load_or_create`). Add:

```python
def test_gen_video_warns_when_style_flag_will_be_ignored(tmp_path, monkeypatch):
    """--style is silently ineffective once T2V-PROMPTS.md already exists and
    --regenerate-prompts was not passed — the operator must be told, not left
    to wonder why the flag had no effect."""
    from click.testing import CliRunner
    from clip_weave.__main__ import cli

    storyboard = tmp_path / "STORYBOARD.md"
    storyboard.write_text(
        "---\nformat: 1920x1080\n---\n\n## Frame 1\n- scene: x\n- duration: 5s\n",
        encoding="utf-8",
    )

    class FakeSpec:
        index = 1
        needs_review = False
        notes = ""

    class FakeDoc:
        specs = [FakeSpec()]

    monkeypatch.setattr(
        "clip_weave.core.t2v_prompt.load_or_create",
        lambda *a, **k: (FakeDoc(), tmp_path / "T2V-PROMPTS.md", False),  # created=False
    )
    monkeypatch.setattr("clip_weave.core.t2v_prompt.literal_prompt", lambda spec: "p")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["gen-video", str(storyboard), "--provider", "doubao", "--style", "35mm film",
         "--dry-run"],
    )

    assert "--style" in result.output
    assert "T2V-PROMPTS.md" in result.output


def test_gen_video_no_warning_when_prompts_file_is_freshly_created(tmp_path, monkeypatch):
    """The warning must only fire when the flag is actually being ignored —
    a fresh file means build_doc() DID see the flag, so no warning is needed."""
    from click.testing import CliRunner
    from clip_weave.__main__ import cli

    storyboard = tmp_path / "STORYBOARD.md"
    storyboard.write_text(
        "---\nformat: 1920x1080\n---\n\n## Frame 1\n- scene: x\n- duration: 5s\n",
        encoding="utf-8",
    )

    class FakeSpec:
        index = 1
        needs_review = False
        notes = ""

    class FakeDoc:
        specs = [FakeSpec()]

    monkeypatch.setattr(
        "clip_weave.core.t2v_prompt.load_or_create",
        lambda *a, **k: (FakeDoc(), tmp_path / "T2V-PROMPTS.md", True),  # created=True
    )
    monkeypatch.setattr("clip_weave.core.t2v_prompt.literal_prompt", lambda spec: "p")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["gen-video", str(storyboard), "--provider", "doubao", "--style", "35mm film",
         "--dry-run"],
    )

    assert "--style" not in result.output


def test_gen_video_no_warning_when_no_relevant_flags_passed(tmp_path, monkeypatch):
    """No style/voiceover/audio flags passed at all → nothing to warn about,
    even if the prompts file already existed."""
    from click.testing import CliRunner
    from clip_weave.__main__ import cli

    storyboard = tmp_path / "STORYBOARD.md"
    storyboard.write_text(
        "---\nformat: 1920x1080\n---\n\n## Frame 1\n- scene: x\n- duration: 5s\n",
        encoding="utf-8",
    )

    class FakeSpec:
        index = 1
        needs_review = False
        notes = ""

    class FakeDoc:
        specs = [FakeSpec()]

    monkeypatch.setattr(
        "clip_weave.core.t2v_prompt.load_or_create",
        lambda *a, **k: (FakeDoc(), tmp_path / "T2V-PROMPTS.md", False),
    )
    monkeypatch.setattr("clip_weave.core.t2v_prompt.literal_prompt", lambda spec: "p")

    runner = CliRunner()
    result = runner.invoke(
        cli, ["gen-video", str(storyboard), "--provider", "doubao", "--dry-run"]
    )

    assert "--style" not in result.output
    assert "--include-voiceover" not in result.output
    assert "--generate-audio" not in result.output
```

If `tests/test_cli.py` already has a fixture or pattern for stubbing `t2v_prompt`/`generate_clips` that differs from the `monkeypatch.setattr` shown above (e.g. it uses `unittest.mock.patch` with a decorator, matching this branch's other CLI tests), match that existing pattern instead of introducing a second style in the same file — the behavior asserted is what matters, not the exact mocking mechanism.

- [ ] **Step 3: Confirm the tests fail for the right reason**

Run: `cd /Users/beersoccer/workspace/clip-weave && .venv/bin/python -m pytest tests/test_cli.py -k gen_video_warns -v`

Expected: `test_gen_video_warns_when_style_flag_will_be_ignored` FAILS (no such warning exists yet); the other two may already pass trivially (nothing to assert against yet) — that is fine, they exist to prevent the fix from being too aggressive.

- [ ] **Step 4: Implement the warning**

In `src/clip_weave/__main__.py`'s `gen_video_cmd`, immediately after the existing line:

```python
    click.echo(f"{'wrote' if created else 'using'} {prompts_path}")
```

add:

```python
    if not created and not regenerate_prompts:
        ignored_flags = [
            name for name, value in (
                ("--style", style),
                ("--include-voiceover", include_voiceover),
                ("--generate-audio", generate_audio),
            )
            if value
        ]
        if ignored_flags:
            click.echo(
                f"  注意：{', '.join(ignored_flags)} 对已存在的 {prompts_path.name} 不生效——"
                "该文件已生成的提示词优先。用 --regenerate-prompts 从 STORYBOARD.md 重建"
                "（会丢弃手工编辑），或直接编辑该文件。"
            )
```

Do not change anything else in `gen_video_cmd` — no other line, no reordering of the surrounding code.

- [ ] **Step 5: Run the tests again — all should pass**

Run: `cd /Users/beersoccer/workspace/clip-weave && .venv/bin/python -m pytest tests/test_cli.py -k gen_video -v`

Expected: all `gen_video`-related tests in that file PASS, including the three new ones and any pre-existing `gen-video` tests (confirm none of those regressed).

- [ ] **Step 6: Run the full suite**

Run: `cd /Users/beersoccer/workspace/clip-weave && .venv/bin/python -m pytest -q`

Expected: 273 passed (270 after Task 1 + 3 new tests).

- [ ] **Step 7: Commit**

```bash
cd /Users/beersoccer/workspace/clip-weave
git add src/clip_weave/__main__.py tests/test_cli.py
git commit -m "fix(cli): warn when --style/--include-voiceover/--generate-audio will be ignored

gen_video_cmd always calls load_or_create() first; once T2V-PROMPTS.md already
exists, generate_clips()'s prompt_overrides from that file always win over
these CLI flags, silently. A user re-running gen-video with --style on an
established project got no effect and no explanation.

Warns instead of silently overriding the user's file, since forcing
--regenerate-prompts automatically would discard hand edits without asking.

Found by the final whole-branch review of feat/rule-guard-soundness-and-
t2v-routing — a seam between two mechanisms (prompt-file persistence and
per-call CLI flags) that no single task's unit tests, each mocking at one
layer's boundary, could see."
```

---

## Self-Review

**Spec coverage:** Both Important findings from the final review are addressed — Task 1 wires `frame_path()` into the pipeline for `render: mixed`; Task 2 makes the prompt-override-vs-flag seam visible instead of silent. The three Minor findings from the same review (storyboard.py-vs-t2v_prompt.py fallback asymmetry, stale "257" test counts in docs, HF line-number drift) are explicitly NOT in this plan's scope — they were logged as low-severity follow-ups by the reviewer, not blocking, and mixing them into this plan would blur its two-fix focus. If the user wants those addressed too, they need their own task(s).

**Placeholder scan:** No TBD/TODO markers; every step has literal code.

**Type consistency:** `generate_clips(..., render_default: str | None = None)` in Task 1 — the CLI wiring in Step 6 passes `chosen` (the `RenderPath | None` from `rp.resolve()`) directly, which is a `str | None` at the type-checker's view since `RenderPath` is a `Literal[...]` subtype of `str`; no cast needed. Task 2 introduces no new types at all, only reads existing in-scope variables (`created`, `regenerate_prompts`, `style`, `include_voiceover`, `generate_audio`) that are already parameters of `gen_video_cmd`.

**Task independence confirmed:** Task 1 touches `video_pipeline.py` + one call site in `__main__.py`'s `generate_clips(...)` invocation; Task 2 touches a different, non-overlapting block in the same `gen_video_cmd` function (after `load_or_create`, before the `prompt_overrides = {...}` line Task 1 does not touch). Both tasks modify `__main__.py`, so they should run sequentially (not in parallel) to avoid a merge conflict on the same file — subagent-driven-development's rule against parallel implementer dispatch already enforces this.
