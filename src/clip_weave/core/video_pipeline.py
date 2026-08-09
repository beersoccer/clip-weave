"""STORYBOARD.md → AI-generated clips.

One storyboard frame becomes one generation task. All tasks are submitted
first (the providers queue them server-side), then polled together, then each
finished clip is downloaded next to the storyboard:

    <storyboard dir>/renders/ai-clips/<provider>/01-<slug>.mp4
    <storyboard dir>/renders/ai-clips/<provider>/manifest.json
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import stat
import tempfile
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Literal
from urllib.parse import urlparse

import shutil
import subprocess

from clip_weave.adapters.video_gen import (
    TaskStatus,
    VideoGenError,
    VideoModel,
    VideoRequest,
    get_model,
    looks_like_project_id,
    resolve_project,
)
from clip_weave.core.render_path import ProfileError, validate_frames
from clip_weave.core.generation_preflight import preflight_request
from clip_weave.core.proof_media import ResolvedReference, materialize_reference
from clip_weave.core.storyboard import (
    Frame,
    Storyboard,
    build_prompt,
    frame_negative_prompt,
    parse_storyboard,
)

logger = logging.getLogger(__name__)

Reporter = Callable[[str], None]


def _safe_reporter(report: Reporter) -> Reporter:
    """Wrap a `report` callback so a broken sink (dead pty, closed pipe, a UI
    callback that raises) can never take down the generation loop with it.

    `report` is a progress side-channel, not part of the task's outcome — a
    clip that finished downloading is finished regardless of whether printing
    "done" succeeds. Before this wrapper, a `report()` call sat inside the
    download `try/except`, so a failure or a slow/blocked write there could
    either mislabel a successful download as failed, or (if the underlying
    write blocks instead of raising, e.g. a stalled pty) hang the whole
    submit/poll/download loop forever with no further output and no
    manifest.json ever written — indistinguishable from the process looking
    "stuck" from the outside.
    """

    def _wrapped(message: str) -> None:
        try:
            report(message)
        except Exception:  # noqa: BLE001 - a broken progress sink must never abort generation
            logger.warning("report sink failed for message: %s", message[:200], exc_info=True)

    return _wrapped


@dataclass
class ClipResult:
    index: int
    title: str
    prompt: str
    duration: int
    request_fingerprint: str | None = None
    task_id: str | None = None
    state: str = "pending"
    video_path: str | None = None
    artifact_sha256: str | None = None
    video_url: str | None = None
    inline_payload_path: str | None = None
    error: str | None = None
    elapsed_seconds: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


_MANIFEST_SCHEMA_VERSION = 2


def _request_fingerprint(
    *, provider: str, model: str, index: int, request: VideoRequest, audit: dict[str, Any]
) -> str:
    payload = {
        "provider": provider,
        "model": model,
        "index": index,
        "prompt": request.prompt,
        "duration": request.duration,
        "ratio": request.ratio,
        "resolution": request.resolution,
        "negative_prompt": request.negative_prompt,
        "seed": request.seed,
        "generate_audio": request.generate_audio,
        "watermark": request.watermark,
        "preflight_audit": audit,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _proof_media_identity(snapshot: dict[str, object]) -> dict[str, object]:
    """Keep request identity to provider-visible media, not human provenance."""
    return {key: snapshot[key] for key in ("sha256", "uri", "scheme") if key in snapshot}


def _fingerprint_reference_audit(audit: dict[str, object]) -> dict[str, object]:
    """Exclude the local provenance path from durable provider task identity."""
    return {key: value for key, value in audit.items() if key != "requested"}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_hash_matches(result: ClipResult) -> bool:
    artifact_sha256 = result.artifact_sha256
    if not (
        isinstance(artifact_sha256, str)
        and len(artifact_sha256) == 64
        and all(char in "0123456789abcdef" for char in artifact_sha256)
        and result.video_path
    ):
        return False
    try:
        path = Path(result.video_path)
        return stat.S_ISREG(path.lstat().st_mode) and _sha256_file(path) == artifact_sha256
    except OSError:
        return False


def _download_destination(out: Path, index: int, slug: str) -> Path:
    """Choose a destination without replacing an existing artifact."""
    standard = out / f"{index:02d}-{slug}.mp4"
    if not os.path.lexists(standard):
        return standard

    for number in range(1, 1_000_000):
        recovered = standard.with_name(
            f"{standard.stem}.recovered-{number}{standard.suffix}"
        )
        if not os.path.lexists(recovered):
            return recovered
    raise VideoGenError(f"no available recovery destination for frame {index} in {out}")


def _atomic_write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".manifest-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(manifest, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        _fsync_parent_directory(path)
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)


def _fsync_parent_directory(path: Path) -> None:
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _atomic_write_inline_payload(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".payload-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        _fsync_parent_directory(path)
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)


def _inline_payload_path(out: Path, clip: ClipResult) -> Path:
    return out / f".{clip.index:02d}-{clip.request_fingerprint}.base64"


def _load_manifest(path: Path, context: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return {**context, "schema_version": _MANIFEST_SCHEMA_VERSION, "clips": []}
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VideoGenError(f"invalid manifest {path}: {exc}") from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get("clips"), list):
        raise VideoGenError(f"invalid manifest {path}: expected an object with a clips list")
    manifest.update(context)
    manifest["schema_version"] = _MANIFEST_SCHEMA_VERSION
    return manifest


def _clip_from_record(record: dict[str, Any], manifest_path: Path) -> ClipResult:
    try:
        return ClipResult(
            index=int(record["index"]),
            title=str(record["title"]),
            prompt=str(record["prompt"]),
            duration=int(record["duration"]),
            request_fingerprint=record.get("request_fingerprint"),
            task_id=record.get("task_id"),
            state=str(record.get("state") or "pending"),
            video_path=record.get("video_path"),
            artifact_sha256=record.get("artifact_sha256"),
            video_url=record.get("video_url"),
            inline_payload_path=record.get("inline_payload_path"),
            error=record.get("error"),
            elapsed_seconds=record.get("elapsed_seconds"),
            extra=dict(record.get("extra") or {}),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise VideoGenError(f"invalid manifest record in {manifest_path}: {exc}") from exc


def _find_clip(
    manifest: dict[str, Any], manifest_path: Path, index: int, fingerprint: str
) -> ClipResult | None:
    for record in reversed(manifest["clips"]):
        if not isinstance(record, dict):
            continue
        if record.get("index") == index and record.get("request_fingerprint") == fingerprint:
            return _clip_from_record(record, manifest_path)
    return None


def _persist_clip(path: Path, manifest: dict[str, Any], clip: ClipResult) -> None:
    record = asdict(clip)
    for position in range(len(manifest["clips"]) - 1, -1, -1):
        existing = manifest["clips"][position]
        if (
            isinstance(existing, dict)
            and existing.get("index") == clip.index
            and existing.get("request_fingerprint") == clip.request_fingerprint
        ):
            manifest["clips"][position] = record
            break
    else:
        manifest["clips"].append(record)
    manifest["schema_version"] = _MANIFEST_SCHEMA_VERSION
    _atomic_write_manifest(path, manifest)


def _download_clip(
    vm: VideoModel,
    result: ClipResult,
    status: TaskStatus,
    *,
    out: Path,
    storyboard: Storyboard,
    manifest_path: Path,
    manifest: dict[str, Any],
    report: Reporter,
) -> None:
    slug = _slug_for(storyboard, result.index)
    while True:
        dest = _download_destination(out, result.index, slug)
        temp: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=dest.parent,
                prefix=f".{dest.name}-",
                suffix=".part",
                delete=False,
            ) as handle:
                temp = Path(handle.name)
            vm.download(status, temp)
            try:
                os.link(temp, dest)
            except FileExistsError:
                temp.unlink(missing_ok=True)
                continue
            temp.unlink()
            result.artifact_sha256 = _sha256_file(dest)
        except Exception as exc:  # noqa: BLE001 - download/IO surface
            if temp:
                temp.unlink(missing_ok=True)
            result.state = "download_pending"
            result.artifact_sha256 = None
            result.error = f"download failed: {exc}"
            _persist_clip(manifest_path, manifest, result)
            logger.error("frame %s download failed: %s", result.index, exc)
            return
        break
    result.state = "succeeded"
    result.video_path = str(dest)
    result.error = None
    inline_payload_path = result.inline_payload_path
    result.inline_payload_path = None
    _persist_clip(manifest_path, manifest, result)
    if inline_payload_path:
        try:
            Path(inline_payload_path).unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("frame %s could not remove inline payload: %s", result.index, exc)
    report(f"frame {result.index} done in {result.elapsed_seconds}s → {dest}")


def generate_clips(
    storyboard_path: str | Path,
    *,
    provider: str,
    out_dir: str | Path | None = None,
    frames: list[int] | None = None,
    resolution: str = "1080p",
    ratio: str | None = None,
    duration: int | None = None,
    include_voiceover: bool = False,
    generate_audio: bool = False,
    watermark: bool = False,
    style: str | None = None,
    seed: int | None = None,
    poll_interval: int = 10,
    max_wait: int = 900,
    dry_run: bool = False,
    model: VideoModel | None = None,
    report: Reporter = logger.info,
    prompt_overrides: dict[int, str] | None = None,
    duration_overrides: dict[int, int] | None = None,
    negative_overrides: dict[int, str] | None = None,
    reference_overrides: dict[int, str] | None = None,
    reference_requirements: dict[int, Literal["optional", "required"]] | None = None,
    reference_sources: dict[int, str] | None = None,
    reference_licenses: dict[int, str] | None = None,
) -> list[ClipResult]:
    """Generate one clip per storyboard frame with the chosen provider."""
    report = _safe_reporter(report)
    sb = parse_storyboard(storyboard_path)
    for warn in sb.warnings:
        logger.warning("storyboard: %s", warn)
    if not sb.frames:
        raise VideoGenError(f"no frames parsed from {storyboard_path}")
    try:
        validate_frames([frame.meta for frame in sb.frames])
    except ProfileError as exc:
        raise VideoGenError(str(exc)) from exc

    selected = _select(sb, frames)
    target_ratio = ratio or sb.aspect_ratio()
    prompt_overrides = prompt_overrides or {}
    duration_overrides = duration_overrides or {}
    negative_overrides = negative_overrides or {}
    reference_overrides = reference_overrides or {}
    reference_requirements = reference_requirements or {}
    reference_sources = reference_sources or {}
    reference_licenses = reference_licenses or {}

    def prompt_for(frame: Frame) -> str:
        # T2V-PROMPTS.md wins when present — that is the file the user edits.
        return prompt_overrides.get(frame.index) or build_prompt(
            sb, frame, include_voiceover=include_voiceover, style=style
        )

    if dry_run:
        report("[dry-run] provider capability check not performed")
        results = []
        for frame in selected:
            prompt = prompt_for(frame)
            results.append(
                ClipResult(
                    index=frame.index,
                    title=frame.title,
                    prompt=prompt,
                    duration=duration or duration_overrides.get(frame.index)
                    or int(frame.duration_seconds or 5),
                    state="dry-run",
                    extra={
                        "ratio": target_ratio,
                        "resolution": resolution,
                        "provider_capability_check": "not performed (dry-run)",
                    },
                )
            )
            report(f"[dry-run] frame {frame.index} ({frame.title}) {len(prompt)} chars\n  {prompt}")
        return results

    vm = model or _build_model(provider, storyboard_path, report=report)

    preflight_by_index = {}
    proof_media_by_index: dict[int, dict[str, object]] = {}
    preflight_errors: list[str] = []
    for frame in selected:
        prompt = prompt_for(frame)
        reference = reference_overrides.get(frame.index) or ""
        resolved = ResolvedReference(reference or None, reference or None, None)
        scheme = urlparse(reference).scheme.lower()
        if reference and scheme not in vm.capabilities.reference_uri_schemes:
            try:
                resolved = materialize_reference(
                    reference,
                    project_dir=Path(storyboard_path).parent,
                    supported_schemes=vm.capabilities.reference_uri_schemes,
                    source_note=reference_sources.get(frame.index),
                    license_note=reference_licenses.get(frame.index),
                )
            except VideoGenError as exc:
                if reference_requirements.get(frame.index) == "required":
                    preflight_errors.append(f"frame {frame.index}: required reference materialization failed: {exc}")
                    continue
        request = VideoRequest(
            prompt=prompt,
            duration=duration or duration_overrides.get(frame.index) or int(frame.duration_seconds or 5),
            ratio=target_ratio,
            resolution=resolution,
            negative_prompt=negative_overrides.get(frame.index) or frame_negative_prompt(frame),
            seed=seed,
            generate_audio=generate_audio,
            watermark=watermark,
            image_url=resolved.applied,
        )
        try:
            capabilities = vm.capabilities
            if reference and not scheme and resolved.applied != reference:
                capabilities = replace(
                    capabilities,
                    reference_uri_schemes=capabilities.reference_uri_schemes | frozenset({""}),
                )
            preflight = preflight_request(
                request,
                capabilities,
                reference=reference or None,
                reference_requirement=reference_requirements.get(frame.index),
            )
            if resolved.applied != reference:
                preflight = replace(
                    preflight,
                    request=replace(preflight.request, image_url=resolved.applied),
                    reference_audit=replace(preflight.reference_audit, applied=resolved.applied),
                )
            preflight_by_index[frame.index] = preflight
            if resolved.proof_media is not None:
                proof_media_by_index[frame.index] = resolved.proof_media
        except VideoGenError as exc:
            preflight_errors.append(f"frame {frame.index}: {exc}")
    if preflight_errors:
        raise VideoGenError("preflight failed: " + "; ".join(preflight_errors))

    out = Path(out_dir) if out_dir else Path(storyboard_path).parent / "renders" / "ai-clips" / provider
    out.mkdir(parents=True, exist_ok=True)

    manifest_path = out / "manifest.json"
    manifest = _load_manifest(
        manifest_path,
        {
            "storyboard": str(Path(storyboard_path).resolve()),
            "provider": provider,
            "model": vm.model,
            "resolution": resolution,
            "ratio": target_ratio,
        },
    )
    results: list[ClipResult] = []
    started: dict[int, float] = {}

    # ── submit or resume ─────────────────────────────────────────────────────
    for frame in selected:
        preflight = preflight_by_index[frame.index]
        request = preflight.request
        result = ClipResult(
            index=frame.index,
            title=frame.title,
            prompt=request.prompt,
            duration=request.duration,
            extra={
                "ratio": target_ratio,
                "resolution": resolution,
                "model": vm.model,
                "requested_parameters": preflight.requested_parameters,
                "applied_parameters": preflight.applied_parameters,
                "reference_audit": asdict(preflight.reference_audit),
            },
        )
        if frame.index in proof_media_by_index:
            result.extra["proof_media"] = proof_media_by_index[frame.index]
        audit = {
            "requested_parameters": preflight.requested_parameters,
            "applied_parameters": preflight.applied_parameters,
            "reference_audit": _fingerprint_reference_audit(asdict(preflight.reference_audit)),
        }
        if frame.index in proof_media_by_index:
            audit["proof_media"] = _proof_media_identity(proof_media_by_index[frame.index])
        result.request_fingerprint = _request_fingerprint(
            provider=provider,
            model=vm.model,
            index=frame.index,
            request=request,
            audit=audit,
        )
        existing = _find_clip(manifest, manifest_path, frame.index, result.request_fingerprint)
        if existing:
            if existing.state == "succeeded":
                if _artifact_hash_matches(existing):
                    results.append(existing)
                    continue
                existing.video_path = None
                existing.artifact_sha256 = None
                existing.error = "artifact integrity check failed"
                if existing.video_url or existing.inline_payload_path:
                    existing.state = "download_pending"
                elif existing.task_id:
                    existing.state = "running"
                else:
                    existing.state = "failed"
                _persist_clip(manifest_path, manifest, existing)
            results.append(existing)
            continue

        result.state = "submitting"
        _persist_clip(manifest_path, manifest, result)
        try:
            result.task_id = vm.submit(request)
        except VideoGenError as exc:
            result.error = str(exc)
            _persist_clip(manifest_path, manifest, result)
            logger.error("frame %s submit outcome is unknown: %s", frame.index, exc)
            results.append(result)
            continue
        result.state, result.error = "running", None
        _persist_clip(manifest_path, manifest, result)
        started[frame.index] = time.time()
        report(f"submitted frame {frame.index} ({frame.title or '—'}) → {result.task_id}")
        results.append(result)

    # ── download recovered provider successes ─────────────────────────────────
    for result in results:
        if result.state != "download_pending":
            continue
        if not result.video_url and not result.inline_payload_path:
            if result.task_id:
                result.state = "running"
                _persist_clip(manifest_path, manifest, result)
            continue
        video_b64 = None
        if result.inline_payload_path:
            try:
                video_b64 = Path(result.inline_payload_path).read_text(encoding="utf-8")
            except OSError as exc:
                result.error = f"inline payload unavailable: {exc}"
                _persist_clip(manifest_path, manifest, result)
                logger.error("frame %s inline payload unavailable: %s", result.index, exc)
                continue
        _download_clip(
            vm,
            result,
            TaskStatus(
                state="succeeded",
                raw={},
                video_url=result.video_url,
                video_b64=video_b64,
            ),
            out=out,
            storyboard=sb,
            manifest_path=manifest_path,
            manifest=manifest,
            report=report,
        )

    # ── poll ─────────────────────────────────────────────────────────────────
    pending = [r for r in results if r.state == "running" and r.task_id]
    for result in pending:
        started.setdefault(result.index, time.time())
    deadline = time.time() + max_wait
    while pending and time.time() < deadline:
        time.sleep(poll_interval)
        still: list[ClipResult] = []
        for result in pending:
            try:
                status = vm.poll(result.task_id)  # type: ignore[arg-type]
            except VideoGenError as exc:
                result.error = str(exc)
                _persist_clip(manifest_path, manifest, result)
                logger.error("frame %s poll failed: %s", result.index, exc)
                continue
            if status.state in ("pending", "running"):
                if result.error:
                    result.error = None
                    _persist_clip(manifest_path, manifest, result)
                still.append(result)
                continue
            result.elapsed_seconds = round(time.time() - started.get(result.index, time.time()), 1)
            if status.state == "failed":
                result.state, result.error = "failed", status.error or "task failed"
                _persist_clip(manifest_path, manifest, result)
                logger.error("frame %s failed: %s", result.index, result.error)
                continue
            result.video_url = status.video_url
            if status.video_b64:
                inline_payload_path = _inline_payload_path(out, result)
                _atomic_write_inline_payload(inline_payload_path, status.video_b64)
                result.inline_payload_path = str(inline_payload_path)
            result.state = "download_pending"
            _persist_clip(manifest_path, manifest, result)
            _download_clip(
                vm,
                result,
                status,
                out=out,
                storyboard=sb,
                manifest_path=manifest_path,
                manifest=manifest,
                report=report,
            )
        pending = still

    for result in pending:
        result.error = f"wait budget elapsed after {max_wait}s"
        _persist_clip(manifest_path, manifest, result)

    report(f"manifest: {manifest_path}")
    return results


def _build_model(provider: str, storyboard_path: str | Path, *, report: Reporter) -> VideoModel:
    """Construct the provider client, auto-resolving Vertex's GCP project."""
    if provider != "vertex":
        return get_model(provider)

    from clip_weave.adapters.video_gen.vertex import load_config

    if (load_config().extra.get("MODEL_PATH") or "").strip():
        return get_model("vertex")  # caller pinned the full resource path

    project, source = resolve_project(storyboard_path)
    if not project:
        raise VideoGenError(
            "vertex: no GCP project id found. Vertex's resource path is "
            "projects/{project}/locations/{location}/publishers/google/models/{model} — "
            "there is no path without a real GCP project id in it (an arbitrary name "
            "returns 403 CONSUMER_INVALID). Set VERTEX_VIDEO_PROJECT in .env, or add "
            "`vertex_project: <project-id>` to BRIEF.md / the storyboard frontmatter, "
            "or set VERTEX_VIDEO_MODEL_PATH to the full resource path."
        )
    if not looks_like_project_id(project):
        logger.warning(
            "vertex: %r (from %s) does not look like a GCP project id — "
            "it must be the cloud project, not the video project name",
            project,
            source,
        )
    report(f"vertex: using GCP project {project} (from {source})")
    return get_model("vertex", PROJECT=project)


def concat_clips(results: list[ClipResult], dest: Path, *, report: Reporter = logger.info) -> Path:
    """Stitch the finished clips into one mp4, in storyboard order, via ffmpeg.

    Needed because every provider caps a single generation well below a full
    video (Veo: 4/6/8s per call, Seedance/Wan: 5–15s), so a storyboard always
    comes back as N clips.
    """
    report = _safe_reporter(report)
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise VideoGenError("ffmpeg not found on PATH — install it to use --concat")

    clips = [r for r in sorted(results, key=lambda r: r.index) if r.video_path]
    if not clips:
        raise VideoGenError("nothing to concatenate — no clip finished successfully")

    dest.parent.mkdir(parents=True, exist_ok=True)
    listing = dest.parent / f".{dest.stem}-concat.txt"
    listing.write_text(
        "".join(f"file '{Path(c.video_path).resolve()}'\n" for c in clips), encoding="utf-8"
    )
    cmd = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
           "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
           "-c:a", "aac", str(dest)]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    listing.unlink(missing_ok=True)
    if proc.returncode != 0:
        raise VideoGenError(f"ffmpeg concat failed:\n{proc.stderr[-800:]}")
    report(f"concatenated {len(clips)} clips → {dest}")
    return dest


def _select(sb: Storyboard, frames: list[int] | None) -> list[Frame]:
    if not frames:
        return sb.frames
    wanted = set(frames)
    picked = [f for f in sb.frames if f.index in wanted or (f.number and f.number in wanted)]
    missing = wanted - {f.index for f in picked} - {f.number for f in picked if f.number}
    if missing:
        logger.warning("frames not found in storyboard: %s", sorted(missing))
    return picked


def _slug_for(sb: Storyboard, index: int) -> str:
    for frame in sb.frames:
        if frame.index == index:
            return frame.slug()
    return f"frame-{index}"


__all__ = ["ClipResult", "concat_clips", "generate_clips"]
