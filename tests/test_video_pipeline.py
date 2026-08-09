"""Offline tests for the storyboard → clips pipeline.

generate_clips() accepts `model=`, so every test injects a FakeModel and no
network, ffmpeg binary, or gateway is touched.
"""

import hashlib
import json
import os
from pathlib import Path

import pytest

from clip_weave.adapters.video_gen import ProviderCapabilities, TaskStatus, VideoGenError
from clip_weave.core import proof_media, video_pipeline
from clip_weave.core.proof_media import ResolvedReference
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

    def __init__(
        self,
        *,
        submit_error=None,
        crash_on_submit_number=None,
        polls=None,
        poll_error=None,
        download_error=None,
        capabilities=None,
    ):
        self.submit_error = submit_error
        self.crash_on_submit_number = crash_on_submit_number
        self.polls = polls or {}
        self.poll_error = poll_error
        self.download_error = download_error
        self.capabilities = capabilities or ProviderCapabilities(
            ratios=frozenset({"16:9", "9:16", "1:1"}),
            resolutions=frozenset({"480p", "720p", "1080p"}),
            duration_range=(5, 10),
            reference_uri_schemes=frozenset({"http", "https"}),
        )
        self.submitted = []
        self.polled = []
        self.downloaded = []
        self.download_statuses = []
        self._poll_counts = {}

    def clamp_duration(self, seconds):
        return int(seconds or 5)

    def submit(self, req):
        self.submitted.append(req)
        if self.crash_on_submit_number == len(self.submitted):
            raise RuntimeError("simulated process stop")
        if self.submit_error:
            raise VideoGenError(self.submit_error)
        return f"task-{len(self.submitted)}"

    def poll(self, task_id):
        self.polled.append(task_id)
        if self.poll_error:
            raise VideoGenError(self.poll_error)
        n = self._poll_counts.get(task_id, 0)
        self._poll_counts[task_id] = n + 1
        scripted = self.polls.get(task_id)
        if scripted is None:
            return TaskStatus(state="succeeded", raw={}, video_url=f"https://cdn/{task_id}.mp4")
        if isinstance(scripted, list):
            return scripted[min(n, len(scripted) - 1)]
        return scripted

    def download(self, status, dest):
        self.download_statuses.append(status)
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


def _manifest(tmp_path):
    path = tmp_path / "renders" / "ai-clips" / "doubao" / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


# ── dry run ───────────────────────────────────────────────────────────────────

def test_dry_run_builds_prompts_without_a_model(tmp_path):
    results = _run(tmp_path, dry_run=True)

    assert [r.state for r in results] == ["dry-run", "dry-run"]
    assert "第一个镜头" in results[0].prompt
    assert results[0].extra["ratio"] == "16:9"
    assert results[0].duration == 5
    assert not (tmp_path / "renders").exists()  # nothing written


def test_dry_run_never_builds_a_model_or_checks_provider_capabilities(tmp_path, monkeypatch):
    monkeypatch.setattr(
        video_pipeline,
        "_build_model",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must stay offline")),
    )

    results = _run(tmp_path, dry_run=True)

    assert results[0].extra["provider_capability_check"] == "not performed (dry-run)"
    assert not (tmp_path / "renders").exists()


def test_dry_run_reports_provider_capability_check_was_not_performed(tmp_path):
    reports: list[str] = []

    _run(tmp_path, dry_run=True, report=reports.append)

    assert any("provider capability check not performed" in report for report in reports)


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


def test_successful_download_records_artifact_hash_in_result_and_manifest(tmp_path):
    results = _run(tmp_path, model=FakeModel(), frames=[1])

    expected = hashlib.sha256(b"fake mp4 bytes").hexdigest()
    assert results[0].artifact_sha256 == expected
    assert _manifest(tmp_path)["clips"][0]["artifact_sha256"] == expected


def test_manifest_is_written_before_a_later_submit_crashes(tmp_path):
    with pytest.raises(RuntimeError, match="simulated process stop"):
        _run(tmp_path, model=FakeModel(crash_on_submit_number=2))

    manifest = _manifest(tmp_path)
    assert manifest["schema_version"] == 2
    assert manifest["clips"][0]["state"] == "running"
    assert manifest["clips"][0]["task_id"] == "task-1"
    assert manifest["clips"][1]["state"] == "submitting"
    assert manifest["clips"][1]["task_id"] is None


def test_running_task_is_polled_on_repeat_without_resubmission(tmp_path):
    _run(
        tmp_path,
        model=FakeModel(polls={"task-1": TaskStatus(state="running", raw={})}),
        frames=[1],
        max_wait=0,
    )

    resumed = FakeModel(
        polls={
            "task-1": TaskStatus(
                state="succeeded", raw={}, video_url="https://cdn/task-1.mp4"
            )
        }
    )
    results = _run(tmp_path, model=resumed, frames=[1])

    assert [result.state for result in results] == ["succeeded"]
    assert resumed.submitted == []
    assert resumed.downloaded


def test_completed_file_is_reused_without_provider_io(tmp_path):
    _run(tmp_path, model=FakeModel(), frames=[1])

    resumed = FakeModel()
    results = _run(tmp_path, model=resumed, frames=[1])

    assert [result.state for result in results] == ["succeeded"]
    assert resumed.submitted == []
    assert resumed.downloaded == []


def test_completed_file_with_mismatched_artifact_hash_redownloads_without_submit(tmp_path):
    _run(tmp_path, model=FakeModel(), frames=[1])
    manifest = _manifest(tmp_path)
    manifest["clips"][0]["artifact_sha256"] = "0" * 64
    path = tmp_path / "renders" / "ai-clips" / "doubao" / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    resumed = FakeModel()
    results = _run(tmp_path, model=resumed, frames=[1])

    assert [result.state for result in results] == ["succeeded"]
    assert resumed.submitted == []
    assert resumed.polled == []
    assert resumed.downloaded


@pytest.mark.parametrize("artifact_sha256", [None, "not-a-sha", "A" * 64])
def test_completed_file_with_invalid_artifact_hash_redownloads_without_submit(
    tmp_path, artifact_sha256
):
    _run(tmp_path, model=FakeModel(), frames=[1])
    manifest = _manifest(tmp_path)
    manifest["clips"][0]["artifact_sha256"] = artifact_sha256
    path = tmp_path / "renders" / "ai-clips" / "doubao" / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    resumed = FakeModel()
    results = _run(tmp_path, model=resumed, frames=[1])

    assert [result.state for result in results] == ["succeeded"]
    assert resumed.submitted == []
    assert resumed.polled == []
    assert resumed.downloaded


def test_completed_file_with_unreadable_hash_redownloads_without_submit(tmp_path, monkeypatch):
    _run(tmp_path, model=FakeModel(), frames=[1])

    def fail_hash(_path):
        raise OSError("read failed")

    monkeypatch.setattr(video_pipeline, "_sha256_file", fail_hash)
    resumed = FakeModel()
    results = _run(tmp_path, model=resumed, frames=[1])

    assert [result.state for result in results] == ["download_pending"]
    assert resumed.submitted == []
    assert resumed.polled == []
    assert resumed.downloaded


def test_invalid_completed_artifact_with_only_task_id_returns_to_polling(tmp_path):
    _run(
        tmp_path,
        model=FakeModel(polls={"task-1": TaskStatus(state="running", raw={})}),
        frames=[1],
        max_wait=0,
    )
    manifest = _manifest(tmp_path)
    manifest["clips"][0].update(
        state="succeeded",
        video_path="missing.mp4",
        artifact_sha256="0" * 64,
        video_url=None,
        inline_payload_path=None,
    )
    path = tmp_path / "renders" / "ai-clips" / "doubao" / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    resumed = FakeModel(polls={"task-1": TaskStatus(state="failed", raw={}, error="cancelled")})
    results = _run(tmp_path, model=resumed, frames=[1])

    assert [result.state for result in results] == ["failed"]
    assert resumed.submitted == []
    assert resumed.polled == ["task-1"]
    assert resumed.downloaded == []


def test_invalid_completed_artifact_without_recovery_source_fails_without_submit(tmp_path):
    _run(tmp_path, model=FakeModel(), frames=[1])
    manifest = _manifest(tmp_path)
    manifest["clips"][0].update(
        video_path="missing.mp4",
        artifact_sha256="0" * 64,
        video_url=None,
        inline_payload_path=None,
        task_id=None,
    )
    path = tmp_path / "renders" / "ai-clips" / "doubao" / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    resumed = FakeModel()
    results = _run(tmp_path, model=resumed, frames=[1])

    assert [result.state for result in results] == ["failed"]
    assert "artifact integrity check failed" in results[0].error
    assert resumed.submitted == []
    assert resumed.polled == []
    assert resumed.downloaded == []


def test_legacy_manifest_without_fingerprint_does_not_resume_task(tmp_path):
    _run(
        tmp_path,
        model=FakeModel(polls={"task-1": TaskStatus(state="running", raw={})}),
        frames=[1],
        max_wait=0,
    )
    manifest = _manifest(tmp_path)
    manifest["clips"][0].pop("request_fingerprint")
    path = tmp_path / "renders" / "ai-clips" / "doubao" / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    resumed = FakeModel()
    _run(tmp_path, model=resumed, frames=[1])

    assert len(resumed.submitted) == 1


def test_malformed_matching_manifest_record_raises_video_error(tmp_path):
    _run(
        tmp_path,
        model=FakeModel(polls={"task-1": TaskStatus(state="running", raw={})}),
        frames=[1],
        max_wait=0,
    )
    manifest = _manifest(tmp_path)
    manifest["clips"][0].pop("title")
    path = tmp_path / "renders" / "ai-clips" / "doubao" / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(VideoGenError, match=r"invalid manifest record .*manifest.json"):
        _run(tmp_path, model=FakeModel(), frames=[1])


def test_missing_completed_file_redownloads_from_manifest_source(tmp_path):
    _run(tmp_path, model=FakeModel(), frames=[1])
    (tmp_path / "renders" / "ai-clips" / "doubao" / "01-开场.mp4").unlink()

    resumed = FakeModel(download_error="disk full")
    results = _run(tmp_path, model=resumed, frames=[1])

    assert [result.state for result in results] == ["download_pending"]
    assert resumed.submitted == []
    assert resumed.polled == []


def test_missing_completed_file_without_download_source_returns_to_running(tmp_path):
    _run(
        tmp_path,
        model=FakeModel(polls={"task-1": TaskStatus(state="running", raw={})}),
        frames=[1],
        max_wait=0,
    )
    manifest = _manifest(tmp_path)
    manifest["clips"][0]["state"] = "succeeded"
    manifest["clips"][0]["video_path"] = "missing.mp4"
    manifest["clips"][0]["video_url"] = None
    path = tmp_path / "renders" / "ai-clips" / "doubao" / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    resumed = FakeModel(polls={"task-1": TaskStatus(state="running", raw={})})
    results = _run(tmp_path, model=resumed, frames=[1], max_wait=0)

    assert [result.state for result in results] == ["running"]
    assert resumed.submitted == []
    assert resumed.polled == []


def test_changed_request_fingerprint_submits_one_new_task(tmp_path):
    _run(
        tmp_path,
        model=FakeModel(polls={"task-1": TaskStatus(state="running", raw={})}),
        frames=[1],
        max_wait=0,
        seed=1,
    )

    changed = FakeModel()
    _run(tmp_path, model=changed, frames=[1], seed=2)

    assert len(changed.submitted) == 1
    records = [clip for clip in _manifest(tmp_path)["clips"] if clip["index"] == 1]
    assert len({clip["request_fingerprint"] for clip in records}) == 2


def test_required_local_reference_blocks_whole_batch_before_submit_or_output(tmp_path):
    model = FakeModel()

    with pytest.raises(VideoGenError, match=r"frame 2: required reference"):
        _run(
            tmp_path,
            model=model,
            reference_overrides={2: "./keyframe.png"},
            reference_requirements={2: "required"},
        )

    assert model.submitted == []
    assert not (tmp_path / "renders").exists()


def test_required_local_reference_materializes_before_submit_and_records_proof_media(tmp_path, monkeypatch):
    source = tmp_path / "keyframe.png"
    source.write_bytes(b"proof")
    resolved = ResolvedReference(
        requested="./keyframe.png",
        applied="https://cdn.example/keyframe.png",
        proof_media={"sha256": "a" * 64, "uri": "https://cdn.example/keyframe.png", "scheme": "https", "source": "./keyframe.png"},
    )
    monkeypatch.setattr(video_pipeline, "materialize_reference", lambda *args, **kwargs: resolved)
    model = FakeModel()

    _run(
        tmp_path,
        model=model,
        frames=[1],
        reference_overrides={1: "./keyframe.png"},
        reference_requirements={1: "required"},
    )

    assert model.submitted[0].image_url == "https://cdn.example/keyframe.png"
    extra = _manifest(tmp_path)["clips"][0]["extra"]
    assert extra["proof_media"] == resolved.proof_media
    assert extra["reference_audit"]["requested"] == "./keyframe.png"
    assert extra["reference_audit"]["applied"] == "https://cdn.example/keyframe.png"


def test_materialize_reference_selects_supported_store_scheme_and_records_provenance(tmp_path, monkeypatch):
    source = tmp_path / "assets" / "keyframe.png"
    source.parent.mkdir()
    source.write_bytes(b"proof")
    monkeypatch.setenv("PROOF_MEDIA_HTTPS_UPLOAD_URL_TEMPLATE", "https://upload.example/{sha256}{suffix}")
    monkeypatch.setenv("PROOF_MEDIA_HTTPS_URI_TEMPLATE", "https://cdn.example/{sha256}{suffix}")
    monkeypatch.setenv("PROOF_MEDIA_GS_UPLOAD_URL_TEMPLATE", "https://upload.example/{sha256}{suffix}")
    monkeypatch.setenv("PROOF_MEDIA_GS_URI_TEMPLATE", "gs://proof-bucket/{sha256}{suffix}")

    class Response:
        def raise_for_status(self):
            return None

    uploads = []
    monkeypatch.setattr(
        proof_media.requests,
        "put",
        lambda url, *, data, headers: uploads.append((url, data.read(), headers)) or Response(),
    )

    resolved = proof_media.materialize_reference(
        "assets/keyframe.png",
        project_dir=tmp_path,
        supported_schemes=frozenset({"gs"}),
        source_note="Wikimedia Commons",
        license_note="CC BY 4.0",
    )

    assert resolved.applied and resolved.applied.startswith("gs://proof-bucket/")
    assert resolved.proof_media and resolved.proof_media["scheme"] == "gs"
    assert resolved.proof_media["source_note"] == "Wikimedia Commons"
    assert resolved.proof_media["license_note"] == "CC BY 4.0"
    assert uploads and uploads[0][1] == b"proof"
    ledger = json.loads((tmp_path / "renders" / "proof-media.json").read_text())
    assert ledger["records"] == [
        {
            "source": "assets/keyframe.png",
            "sha256": resolved.proof_media["sha256"],
            "suffix": ".png",
            "uri": resolved.applied,
            "scheme": "gs",
            "source_note": "Wikimedia Commons",
            "license_note": "CC BY 4.0",
            "created_at": ledger["records"][0]["created_at"],
        }
    ]


def test_required_materialization_error_blocks_entire_batch_before_submit(tmp_path, monkeypatch):
    monkeypatch.setattr(
        video_pipeline,
        "materialize_reference",
        lambda *args, **kwargs: (_ for _ in ()).throw(VideoGenError("proof media configuration is missing")),
    )
    model = FakeModel()

    with pytest.raises(VideoGenError, match=r"frame 1: required reference materialization failed"):
        _run(
            tmp_path,
            model=model,
            reference_overrides={1: "./keyframe.png"},
            reference_requirements={1: "required"},
        )

    assert model.submitted == []


def test_supported_remote_reference_skips_materialization(tmp_path, monkeypatch):
    monkeypatch.setattr(
        video_pipeline,
        "materialize_reference",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not materialize remote URI")),
    )
    model = FakeModel()

    _run(tmp_path, model=model, frames=[1], reference_overrides={1: "https://cdn.example/keyframe.png"})

    assert model.submitted[0].image_url == "https://cdn.example/keyframe.png"


def test_changed_proof_media_snapshot_does_not_reuse_manifest(tmp_path, monkeypatch):
    source = tmp_path / "keyframe.png"
    source.write_bytes(b"proof")
    snapshots = iter((
        {"sha256": "a" * 64, "uri": "https://cdn.example/a.png", "scheme": "https", "source": "./keyframe.png"},
        {"sha256": "b" * 64, "uri": "https://cdn.example/b.png", "scheme": "https", "source": "./keyframe.png"},
    ))
    monkeypatch.setattr(
        video_pipeline,
        "materialize_reference",
        lambda reference, **kwargs: ResolvedReference(reference, (snapshot := next(snapshots))["uri"], snapshot),
    )
    _run(
        tmp_path,
        model=FakeModel(polls={"task-1": TaskStatus(state="running", raw={})}),
        frames=[1], max_wait=0,
        reference_overrides={1: "./keyframe.png"}, reference_requirements={1: "required"},
    )
    changed = FakeModel()
    _run(
        tmp_path, model=changed, frames=[1], reference_overrides={1: "./keyframe.png"},
        reference_requirements={1: "required"},
    )

    assert len(changed.submitted) == 1


def test_changed_proof_media_provenance_does_not_change_request_fingerprint(tmp_path, monkeypatch):
    snapshots = iter((
        {
            "sha256": "a" * 64,
            "uri": "https://cdn.example/keyframe.png",
            "scheme": "https",
            "source": "./keyframe.png",
            "source_note": "Wikimedia Commons",
            "license_note": "CC BY 4.0",
        },
        {
            "sha256": "a" * 64,
            "uri": "https://cdn.example/keyframe.png",
            "scheme": "https",
            "source": "./keyframe.png",
            "source_note": "Company archive",
            "license_note": "Internal use",
        },
    ))
    monkeypatch.setattr(
        video_pipeline,
        "materialize_reference",
        lambda reference, **kwargs: ResolvedReference(reference, (snapshot := next(snapshots))["uri"], snapshot),
    )
    _run(
        tmp_path,
        model=FakeModel(polls={"task-1": TaskStatus(state="running", raw={})}),
        frames=[1],
        max_wait=0,
        reference_overrides={1: "./keyframe.png"},
        reference_requirements={1: "required"},
    )
    changed = FakeModel()
    _run(
        tmp_path,
        model=changed,
        frames=[1],
        max_wait=0,
        reference_overrides={1: "./keyframe.png"},
        reference_requirements={1: "required"},
    )

    assert changed.submitted == []


def test_changed_local_reference_path_with_same_materialized_media_reuses_manifest(tmp_path, monkeypatch):
    media_identity = {
        "sha256": "a" * 64,
        "uri": "https://cdn.example/keyframe.png",
        "scheme": "https",
    }
    monkeypatch.setattr(
        video_pipeline,
        "materialize_reference",
        lambda reference, **kwargs: ResolvedReference(
            reference,
            media_identity["uri"],
            {**media_identity, "source": reference},
        ),
    )
    _run(
        tmp_path,
        model=FakeModel(polls={"task-1": TaskStatus(state="running", raw={})}),
        frames=[1],
        max_wait=0,
        reference_overrides={1: "assets/first-copy.png"},
        reference_requirements={1: "required"},
    )
    changed = FakeModel()
    _run(
        tmp_path,
        model=changed,
        frames=[1],
        max_wait=0,
        reference_overrides={1: "assets/renamed-copy.png"},
        reference_requirements={1: "required"},
    )

    assert changed.submitted == []


def test_optional_local_reference_without_store_is_dropped_with_exact_audit_in_manifest(tmp_path, monkeypatch):
    for scheme in ("HTTPS", "GS"):
        for name in ("UPLOAD_URL_TEMPLATE", "URI_TEMPLATE", "UPLOAD_HEADERS_JSON"):
            monkeypatch.delenv(f"PROOF_MEDIA_{scheme}_{name}", raising=False)
    _run(
        tmp_path,
        model=FakeModel(),
        frames=[1],
        reference_overrides={1: "./keyframe.png"},
        reference_requirements={1: "optional"},
    )

    extra = _manifest(tmp_path)["clips"][0]["extra"]
    assert extra["reference_audit"] == {
        "requested": "./keyframe.png",
        "requirement": "optional",
        "outcome": "dropped",
        "applied": None,
        "reason": "local reference is not materialized",
    }
    assert extra["requested_parameters"]["duration"] == 5
    assert extra["applied_parameters"]["duration"] == 5
    assert "reference_asset" not in extra


def test_accepted_optional_reference_is_audited_and_submitted(tmp_path):
    model = FakeModel()
    _run(
        tmp_path,
        model=model,
        frames=[1],
        reference_overrides={1: "https://example.com/keyframe.png"},
        reference_requirements={1: "optional"},
    )

    assert model.submitted[0].image_url == "https://example.com/keyframe.png"
    assert _manifest(tmp_path)["clips"][0]["extra"]["reference_audit"]["outcome"] == "accepted"


def test_reference_audit_or_capability_change_does_not_reuse_manifest(tmp_path):
    running = FakeModel(polls={"task-1": TaskStatus(state="running", raw={})})
    _run(
        tmp_path,
        model=running,
        frames=[1],
        max_wait=0,
        reference_overrides={1: "https://example.com/keyframe.png"},
        reference_requirements={1: "optional"},
    )

    changed = FakeModel(
        capabilities=ProviderCapabilities(
            ratios=frozenset({"16:9"}),
            resolutions=frozenset({"1080p"}),
            duration_range=(6, 10),
            reference_uri_schemes=frozenset(),
        )
    )
    _run(
        tmp_path,
        model=changed,
        frames=[1],
        reference_overrides={1: "https://example.com/keyframe.png"},
        reference_requirements={1: "optional"},
    )

    assert len(changed.submitted) == 1


def test_gs_reference_is_forwarded_when_capability_supports_it(tmp_path):
    model = FakeModel(
        capabilities=ProviderCapabilities(
            ratios=frozenset({"16:9"}),
            resolutions=frozenset({"1080p"}),
            duration_range=(5, 10),
            reference_uri_schemes=frozenset({"gs"}),
        )
    )

    _run(
        tmp_path,
        model=model,
        frames=[1],
        reference_overrides={1: "gs://bucket/keyframe.png"},
        reference_requirements={1: "optional"},
    )

    assert model.submitted[0].image_url == "gs://bucket/keyframe.png"


def test_manifest_write_failure_prevents_submit(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "clip_weave.core.video_pipeline._atomic_write_manifest",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
        raising=False,
    )
    model = FakeModel()

    with pytest.raises(OSError, match="disk full"):
        _run(tmp_path, model=model, frames=[1])

    assert model.submitted == []


def test_atomic_manifest_write_syncs_parent_directory(tmp_path, monkeypatch):
    path = tmp_path / "manifest.json"
    directory_fds = []
    synced_fds = []
    real_open = os.open
    real_fsync = os.fsync

    def tracking_open(name, *args, **kwargs):
        fd = real_open(name, *args, **kwargs)
        if Path(name) == path.parent:
            directory_fds.append(fd)
        return fd

    def tracking_fsync(fd):
        synced_fds.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr(video_pipeline.os, "open", tracking_open)
    monkeypatch.setattr(video_pipeline.os, "fsync", tracking_fsync)

    video_pipeline._atomic_write_manifest(path, {"clips": []})

    assert directory_fds
    assert directory_fds[0] in synced_fds


def test_download_failure_stays_download_pending_and_resumes_without_submit(tmp_path):
    first_results = _run(tmp_path, model=FakeModel(download_error="disk full"), frames=[1])
    assert [result.state for result in first_results] == ["download_pending"]

    resumed = FakeModel()
    results = _run(tmp_path, model=resumed, frames=[1])

    assert [result.state for result in results] == ["succeeded"]
    assert resumed.submitted == []
    assert resumed.downloaded


def test_hash_failure_stays_download_pending_without_artifact_hash(tmp_path, monkeypatch):
    def fail_hash(_path):
        raise OSError("disk full")

    monkeypatch.setattr(video_pipeline, "_sha256_file", fail_hash, raising=False)

    results = _run(tmp_path, model=FakeModel(), frames=[1])

    assert results[0].state == "download_pending"
    assert results[0].artifact_sha256 is None
    record = _manifest(tmp_path)["clips"][0]
    assert record["state"] == "download_pending"
    assert record["artifact_sha256"] is None


def test_inline_video_result_resumes_download_without_polling(tmp_path):
    _run(
        tmp_path,
        model=FakeModel(
            polls={
                "task-1": TaskStatus(
                    state="succeeded", raw={}, video_b64="ZmFrZSBtcDQ="
                )
            },
            download_error="disk full",
        ),
        frames=[1],
    )

    resumed = FakeModel()
    results = _run(tmp_path, model=resumed, frames=[1])

    assert [result.state for result in results] == ["succeeded"]
    assert resumed.submitted == []
    assert resumed.polled == []
    assert resumed.downloaded
    assert resumed.download_statuses[0].video_b64 == "ZmFrZSBtcDQ="
    assert "ZmFrZSBtcDQ=" not in json.dumps(_manifest(tmp_path))


def test_timeout_keeps_task_running_for_a_later_resume(tmp_path):
    results = _run(
        tmp_path,
        model=FakeModel(polls={"task-1": TaskStatus(state="running", raw={})}),
        frames=[1],
        max_wait=0,
    )

    assert [result.state for result in results] == ["running"]
    assert _manifest(tmp_path)["clips"][0]["state"] == "running"


def test_transient_poll_error_keeps_task_running(tmp_path):
    results = _run(tmp_path, model=FakeModel(poll_error="gateway unavailable"), frames=[1])

    assert [result.state for result in results] == ["running"]
    assert "gateway unavailable" in results[0].error


def test_submitting_record_is_never_resubmitted(tmp_path):
    _run(tmp_path, model=FakeModel(submit_error="connection reset"), frames=[1])

    resumed = FakeModel()
    results = _run(tmp_path, model=resumed, frames=[1])

    assert [result.state for result in results] == ["submitting"]
    assert resumed.submitted == []


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

def test_submit_failure_is_retained_as_ambiguous_submission(tmp_path):
    results = _run(tmp_path, model=FakeModel(submit_error="quota exceeded"))

    assert [r.state for r in results] == ["submitting", "submitting"]
    assert all("quota exceeded" in r.error for r in results)
    assert all(r.task_id is None for r in results)


def test_poll_failure_marks_only_that_frame(tmp_path):
    polls = {"task-1": TaskStatus(state="failed", raw={}, error="nsfw block")}
    results = _run(tmp_path, model=FakeModel(polls=polls))

    by_index = {r.index: r for r in results}
    assert by_index[1].state == "failed"
    assert by_index[1].error == "nsfw block"
    assert by_index[2].state == "succeeded"


def test_download_failure_remains_download_pending(tmp_path):
    results = _run(tmp_path, model=FakeModel(download_error="disk full"))

    assert [r.state for r in results] == ["download_pending", "download_pending"]
    assert "download failed" in results[0].error
    assert "disk full" in results[0].error


def test_timeout_keeps_pending_frames_running(tmp_path):
    still_running = TaskStatus(state="running", raw={})
    results = _run(
        tmp_path,
        model=FakeModel(polls={"task-1": still_running, "task-2": still_running}),
        max_wait=0,
    )

    assert [r.state for r in results] == ["running", "running"]
    assert all("wait budget elapsed" in r.error for r in results)


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


def test_local_reference_is_audited_but_not_sent(tmp_path):
    """A local capture path cannot be a first frame — it would need uploading."""
    model = FakeModel()
    results = _run(tmp_path, model=model, reference_overrides={1: "capture/assets/hero.png"})

    assert model.submitted[0].image_url is None
    assert results[0].extra["reference_audit"] == {
        "requested": "capture/assets/hero.png",
        "requirement": "optional",
        "outcome": "dropped",
        "applied": None,
        "reason": "local reference is not materialized",
    }
    assert "reference_asset" not in results[0].extra


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
