"""Offline tests for the storyboard → clips pipeline.

generate_clips() accepts `model=`, so every test injects a FakeModel and no
network, ffmpeg binary, or gateway is touched.
"""

import json

import pytest

from clip_weave.adapters.video_gen import TaskStatus, VideoGenError
from clip_weave.core.video_pipeline import ClipResult, concat_clips, generate_clips

STORYBOARD = """---
format: 1920x1080
message: "test message"
---

## Frame 1 — 开场
- scene: 第一个镜头
- duration: 5s

## Frame 2 — 收尾
- scene: 第二个镜头
- duration: 5s
"""


class FakeModel:
    """Stands in for a VideoModel. Scripted per-task poll results."""

    model = "fake-model-1"
    duration_range = (5, 10)
    duration_choices = None

    def __init__(self, *, submit_error=None, polls=None, download_error=None):
        self.submit_error = submit_error
        self.polls = polls or {}
        self.download_error = download_error
        self.submitted = []
        self.downloaded = []
        self._poll_counts = {}

    def clamp_duration(self, seconds):
        return int(seconds or 5)

    def submit(self, req):
        self.submitted.append(req)
        if self.submit_error:
            raise VideoGenError(self.submit_error)
        return f"task-{len(self.submitted)}"

    def poll(self, task_id):
        n = self._poll_counts.get(task_id, 0)
        self._poll_counts[task_id] = n + 1
        scripted = self.polls.get(task_id)
        if scripted is None:
            return TaskStatus(state="succeeded", raw={}, video_url=f"https://cdn/{task_id}.mp4")
        if isinstance(scripted, list):
            return scripted[min(n, len(scripted) - 1)]
        return scripted

    def download(self, status, dest):
        if self.download_error:
            raise OSError(self.download_error)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"fake mp4 bytes")
        self.downloaded.append(dest)
        return dest


def _storyboard(tmp_path, body=STORYBOARD):
    path = tmp_path / "STORYBOARD.md"
    path.write_text(body, encoding="utf-8")
    return path


def _run(tmp_path, body=STORYBOARD, **kwargs):
    """generate_clips with the noisy defaults pinned down."""
    kwargs.setdefault("provider", "doubao")
    kwargs.setdefault("poll_interval", 0)
    kwargs.setdefault("report", lambda _: None)
    return generate_clips(_storyboard(tmp_path, body), **kwargs)


# ── dry run ───────────────────────────────────────────────────────────────────

def test_dry_run_builds_prompts_without_a_model(tmp_path):
    results = _run(tmp_path, dry_run=True)

    assert [r.state for r in results] == ["dry-run", "dry-run"]
    assert "第一个镜头" in results[0].prompt
    assert results[0].extra["ratio"] == "16:9"
    assert results[0].duration == 5
    assert not (tmp_path / "renders").exists()  # nothing written


def test_no_frames_raises(tmp_path):
    body = "---\nformat: 1920x1080\n---\n\nprose only\n"
    with pytest.raises(VideoGenError, match="no frames parsed"):
        _run(tmp_path, body, dry_run=True)


# ── happy path ────────────────────────────────────────────────────────────────

def test_all_frames_succeed_and_files_land(tmp_path):
    model = FakeModel()
    results = _run(tmp_path, model=model)

    assert [r.state for r in results] == ["succeeded", "succeeded"]
    out = tmp_path / "renders" / "ai-clips" / "doubao"
    assert (out / "01-开场.mp4").exists()
    assert (out / "02-收尾.mp4").exists()
    assert len(model.submitted) == 2


def test_manifest_records_run_metadata(tmp_path):
    _run(tmp_path, model=FakeModel())

    manifest = json.loads(
        (tmp_path / "renders" / "ai-clips" / "doubao" / "manifest.json").read_text()
    )
    assert manifest["provider"] == "doubao"
    assert manifest["model"] == "fake-model-1"
    assert manifest["ratio"] == "16:9"
    assert len(manifest["clips"]) == 2
    assert manifest["clips"][0]["state"] == "succeeded"


def test_frames_filter_selects_a_subset(tmp_path):
    model = FakeModel()
    results = _run(tmp_path, model=model, frames=[2])

    assert len(results) == 1
    assert results[0].index == 2
    assert len(model.submitted) == 1


def test_out_dir_override(tmp_path):
    custom = tmp_path / "elsewhere"
    _run(tmp_path, model=FakeModel(), out_dir=custom)
    assert (custom / "manifest.json").exists()


def test_include_voiceover_and_style_reach_the_prompt(tmp_path):
    body = STORYBOARD.replace("- duration: 5s", '- voiceover: "旁白内容"\n- duration: 5s', 1)
    model = FakeModel()
    _run(tmp_path, body, model=model, include_voiceover=True, style="35mm 胶片")

    assert "旁白内容" in model.submitted[0].prompt
    assert "35mm 胶片" in model.submitted[0].prompt


# ── failure paths ─────────────────────────────────────────────────────────────

def test_submit_failure_is_recorded_per_frame(tmp_path):
    results = _run(tmp_path, model=FakeModel(submit_error="quota exceeded"))

    assert [r.state for r in results] == ["failed", "failed"]
    assert all("quota exceeded" in r.error for r in results)
    assert all(r.task_id is None for r in results)


def test_poll_failure_marks_only_that_frame(tmp_path):
    polls = {"task-1": TaskStatus(state="failed", raw={}, error="nsfw block")}
    results = _run(tmp_path, model=FakeModel(polls=polls))

    by_index = {r.index: r for r in results}
    assert by_index[1].state == "failed"
    assert by_index[1].error == "nsfw block"
    assert by_index[2].state == "succeeded"


def test_download_failure_is_reported_as_failed(tmp_path):
    results = _run(tmp_path, model=FakeModel(download_error="disk full"))

    assert [r.state for r in results] == ["failed", "failed"]
    assert "download failed" in results[0].error
    assert "disk full" in results[0].error


def test_timeout_marks_pending_frames_failed(tmp_path):
    still_running = TaskStatus(state="running", raw={})
    results = _run(
        tmp_path,
        model=FakeModel(polls={"task-1": still_running, "task-2": still_running}),
        max_wait=0,
    )

    assert [r.state for r in results] == ["failed", "failed"]
    assert all("timed out" in r.error for r in results)


def test_elapsed_seconds_is_recorded_on_success(tmp_path):
    results = _run(tmp_path, model=FakeModel())
    assert all(r.elapsed_seconds is not None for r in results)


# ── flaky report sink (regression) ───────────────────────────────────────────
#
# `report` is a progress side-channel (CLI echo / pty write) — a failure there
# must never relabel a successful clip as failed, and must never stop the
# pipeline from writing manifest.json for the remaining frames.

def test_report_failure_does_not_fail_a_successful_download(tmp_path):
    def flaky_report(msg):
        if msg.startswith("frame 1 done"):
            raise OSError("broken pipe")

    model = FakeModel()
    results = _run(tmp_path, model=model, report=flaky_report)

    assert [r.state for r in results] == ["succeeded", "succeeded"]
    out = tmp_path / "renders" / "ai-clips" / "doubao"
    assert (out / "01-开场.mp4").exists()


def test_report_failure_does_not_block_manifest_write(tmp_path):
    def always_raises(_msg):
        raise BrokenPipeError("pty gone")

    _run(tmp_path, model=FakeModel(), report=always_raises)

    manifest = tmp_path / "renders" / "ai-clips" / "doubao" / "manifest.json"
    assert manifest.exists()
    data = json.loads(manifest.read_text())
    assert [c["state"] for c in data["clips"]] == ["succeeded", "succeeded"]


def test_concat_report_failure_still_returns_the_stitched_file(tmp_path, monkeypatch):
    monkeypatch.setattr("clip_weave.core.video_pipeline.shutil.which", lambda _: "/usr/bin/ffmpeg")

    class Done:
        returncode = 0
        stderr = ""

    monkeypatch.setattr("clip_weave.core.video_pipeline.subprocess.run", lambda *a, **k: Done())
    (tmp_path / "01.mp4").write_bytes(b"x")
    clip = ClipResult(index=1, title="a", prompt="p", duration=5,
                      video_path=str(tmp_path / "01.mp4"))

    def always_raises(_msg):
        raise OSError("broken pipe")

    dest = concat_clips([clip], tmp_path / "full.mp4", report=always_raises)
    assert dest == tmp_path / "full.mp4"


# ── T2V-PROMPTS.md overrides ──────────────────────────────────────────────────
#
# These four dicts are how a user-edited T2V-PROMPTS.md reaches the provider.

def test_prompt_override_replaces_the_generated_prompt(tmp_path):
    model = FakeModel()
    _run(tmp_path, model=model, prompt_overrides={1: "用户手写的提示词"})

    assert model.submitted[0].prompt == "用户手写的提示词"
    # frame 2 has no override and keeps the generated prompt
    assert "第二个镜头" in model.submitted[1].prompt


def test_prompt_override_applies_in_dry_run(tmp_path):
    results = _run(tmp_path, dry_run=True, prompt_overrides={1: "手写"})
    assert results[0].prompt == "手写"


def test_duration_override_is_used_when_no_explicit_duration(tmp_path):
    model = FakeModel()
    _run(tmp_path, model=model, duration_overrides={1: 10})
    assert model.submitted[0].duration == 10


def test_explicit_duration_beats_the_override(tmp_path):
    """The CLI's --duration is the operator speaking last, so it wins."""
    model = FakeModel()
    _run(tmp_path, model=model, duration=7, duration_overrides={1: 10})
    assert model.submitted[0].duration == 7


def test_negative_override_beats_the_frame_field(tmp_path):
    body = STORYBOARD.replace("- duration: 5s", "- negative_prompt: 帧上的负面\n- duration: 5s", 1)
    model = FakeModel()
    _run(tmp_path, body, model=model, negative_overrides={1: "水印, 文字"})

    assert model.submitted[0].negative_prompt == "水印, 文字"


def test_frame_negative_prompt_is_used_without_an_override(tmp_path):
    body = STORYBOARD.replace("- duration: 5s", "- negative_prompt: 帧上的负面\n- duration: 5s", 1)
    model = FakeModel()
    _run(tmp_path, body, model=model)

    assert model.submitted[0].negative_prompt == "帧上的负面"


def test_remote_reference_becomes_the_first_frame_image(tmp_path):
    model = FakeModel()
    _run(tmp_path, model=model, reference_overrides={1: "https://cdn/hero.png"})
    assert model.submitted[0].image_url == "https://cdn/hero.png"


def test_local_reference_is_recorded_but_not_sent(tmp_path):
    """A local capture path cannot be a first frame — it would need uploading."""
    model = FakeModel()
    results = _run(tmp_path, model=model, reference_overrides={1: "capture/assets/hero.png"})

    assert model.submitted[0].image_url is None
    assert results[0].extra["reference_asset"] == "capture/assets/hero.png"


def test_overrides_default_to_empty_and_change_nothing(tmp_path):
    model = FakeModel()
    results = _run(tmp_path, model=model)

    assert "第一个镜头" in model.submitted[0].prompt
    assert model.submitted[0].negative_prompt is None
    assert model.submitted[0].image_url is None
    assert "reference_asset" not in results[0].extra


# ── concat ────────────────────────────────────────────────────────────────────

def test_concat_requires_ffmpeg(tmp_path, monkeypatch):
    monkeypatch.setattr("clip_weave.core.video_pipeline.shutil.which", lambda _: None)
    clip = ClipResult(index=1, title="t", prompt="p", duration=5,
                      video_path=str(tmp_path / "01.mp4"))
    with pytest.raises(VideoGenError, match="ffmpeg not found"):
        concat_clips([clip], tmp_path / "full.mp4", report=lambda _: None)


def test_concat_with_nothing_finished_raises(tmp_path, monkeypatch):
    monkeypatch.setattr("clip_weave.core.video_pipeline.shutil.which", lambda _: "/usr/bin/ffmpeg")
    failed = ClipResult(index=1, title="t", prompt="p", duration=5, state="failed")
    with pytest.raises(VideoGenError, match="nothing to concatenate"):
        concat_clips([failed], tmp_path / "full.mp4", report=lambda _: None)


def test_concat_orders_clips_and_cleans_the_list_file(tmp_path, monkeypatch):
    monkeypatch.setattr("clip_weave.core.video_pipeline.shutil.which", lambda _: "/usr/bin/ffmpeg")
    recorded = {}

    class Done:
        returncode = 0
        stderr = ""

    def fake_run(cmd, **kwargs):
        recorded["cmd"] = cmd
        listing = cmd[cmd.index("-i") + 1]
        recorded["listing"] = open(listing, encoding="utf-8").read()
        return Done()

    monkeypatch.setattr("clip_weave.core.video_pipeline.subprocess.run", fake_run)

    for name in ("01.mp4", "02.mp4"):
        (tmp_path / name).write_bytes(b"x")
    # deliberately out of storyboard order
    clips = [
        ClipResult(index=2, title="b", prompt="p", duration=5,
                   video_path=str(tmp_path / "02.mp4")),
        ClipResult(index=1, title="a", prompt="p", duration=5,
                   video_path=str(tmp_path / "01.mp4")),
    ]

    dest = tmp_path / "full.mp4"
    assert concat_clips(clips, dest, report=lambda _: None) == dest
    assert recorded["listing"].index("01.mp4") < recorded["listing"].index("02.mp4")
    assert "libx264" in recorded["cmd"]
    assert not (tmp_path / ".full-concat.txt").exists()  # temp list removed


def test_concat_skips_clips_that_never_produced_a_file(tmp_path, monkeypatch):
    monkeypatch.setattr("clip_weave.core.video_pipeline.shutil.which", lambda _: "/usr/bin/ffmpeg")
    recorded = {}

    class Done:
        returncode = 0
        stderr = ""

    def fake_run(cmd, **kwargs):
        recorded["listing"] = open(cmd[cmd.index("-i") + 1], encoding="utf-8").read()
        return Done()

    monkeypatch.setattr("clip_weave.core.video_pipeline.subprocess.run", fake_run)
    (tmp_path / "01.mp4").write_bytes(b"x")
    clips = [
        ClipResult(index=1, title="a", prompt="p", duration=5,
                   video_path=str(tmp_path / "01.mp4")),
        ClipResult(index=2, title="b", prompt="p", duration=5, state="failed"),
    ]

    concat_clips(clips, tmp_path / "full.mp4", report=lambda _: None)
    assert recorded["listing"].count("file '") == 1


def test_concat_surfaces_ffmpeg_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("clip_weave.core.video_pipeline.shutil.which", lambda _: "/usr/bin/ffmpeg")

    class Failed:
        returncode = 1
        stderr = "Invalid data found when processing input"

    monkeypatch.setattr("clip_weave.core.video_pipeline.subprocess.run", lambda *a, **k: Failed())
    (tmp_path / "01.mp4").write_bytes(b"x")
    clip = ClipResult(index=1, title="a", prompt="p", duration=5,
                      video_path=str(tmp_path / "01.mp4"))

    with pytest.raises(VideoGenError, match="ffmpeg concat failed"):
        concat_clips([clip], tmp_path / "full.mp4", report=lambda _: None)


# ── forbidden frame-level renderer directives ─────────────────────────────────

MIXED_STORYBOARD = """---
format: 1920x1080
message: "test message"
---

## Frame 1 — 图表
- scene: 数据柱状图
- render: html
- duration: 5s

## Frame 2 — 实拍
- scene: 城市夜景
- render: t2v
- duration: 5s

## Frame 3 — 未标注
- scene: 第三个镜头
- duration: 5s
"""


def test_t2v_pipeline_rejects_storyboard_with_frame_level_render(tmp_path):
    with pytest.raises(VideoGenError, match="frame-level render"):
        _run(tmp_path, MIXED_STORYBOARD, model=FakeModel())


def test_explicit_frames_do_not_bypass_frame_level_render_validation(tmp_path):
    with pytest.raises(VideoGenError, match="frame-level render"):
        _run(tmp_path, MIXED_STORYBOARD, model=FakeModel(), frames=[2])


def test_t2v_pipeline_generates_every_unannotated_storyboard_frame(tmp_path):
    results = _run(tmp_path, STORYBOARD, model=FakeModel())
    assert [result.index for result in results] == [1, 2]
