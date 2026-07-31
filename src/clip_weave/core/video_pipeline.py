"""STORYBOARD.md → AI-generated clips.

One storyboard frame becomes one generation task. All tasks are submitted
first (the providers queue them server-side), then polled together, then each
finished clip is downloaded next to the storyboard:

    <storyboard dir>/renders/ai-clips/<provider>/01-<slug>.mp4
    <storyboard dir>/renders/ai-clips/<provider>/manifest.json
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

import shutil
import subprocess

from clip_weave.adapters.video_gen import (
    VideoGenError,
    VideoModel,
    VideoRequest,
    get_model,
    looks_like_project_id,
    resolve_project,
)
from clip_weave.core.storyboard import (
    Frame,
    Storyboard,
    build_prompt,
    frame_negative_prompt,
    parse_storyboard,
)

logger = logging.getLogger(__name__)

Reporter = Callable[[str], None]


@dataclass
class ClipResult:
    index: int
    title: str
    prompt: str
    duration: int
    task_id: str | None = None
    state: str = "pending"
    video_path: str | None = None
    video_url: str | None = None
    error: str | None = None
    elapsed_seconds: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


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
) -> list[ClipResult]:
    """Generate one clip per storyboard frame with the chosen provider."""
    sb = parse_storyboard(storyboard_path)
    for warn in sb.warnings:
        logger.warning("storyboard: %s", warn)
    if not sb.frames:
        raise VideoGenError(f"no frames parsed from {storyboard_path}")

    selected = _select(sb, frames)
    target_ratio = ratio or sb.aspect_ratio()
    prompt_overrides = prompt_overrides or {}
    duration_overrides = duration_overrides or {}
    negative_overrides = negative_overrides or {}
    reference_overrides = reference_overrides or {}

    def prompt_for(frame: Frame) -> str:
        # T2V-PROMPTS.md wins when present — that is the file the user edits.
        return prompt_overrides.get(frame.index) or build_prompt(
            sb, frame, include_voiceover=include_voiceover, style=style
        )

    if dry_run:
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
                    extra={"ratio": target_ratio, "resolution": resolution},
                )
            )
            report(f"[dry-run] frame {frame.index} ({frame.title}) {len(prompt)} chars\n  {prompt}")
        return results

    vm = model or _build_model(provider, storyboard_path, report=report)
    out = Path(out_dir) if out_dir else Path(storyboard_path).parent / "renders" / "ai-clips" / provider
    out.mkdir(parents=True, exist_ok=True)

    results: list[ClipResult] = []
    started: dict[int, float] = {}

    # ── submit ───────────────────────────────────────────────────────────────
    for frame in selected:
        prompt = prompt_for(frame)
        secs = vm.clamp_duration(
            duration or duration_overrides.get(frame.index) or frame.duration_seconds
        )
        result = ClipResult(
            index=frame.index,
            title=frame.title,
            prompt=prompt,
            duration=secs,
            extra={"ratio": target_ratio, "resolution": resolution, "model": vm.model},
        )
        reference = reference_overrides.get(frame.index) or ""
        req = VideoRequest(
            prompt=prompt,
            duration=secs,
            ratio=target_ratio,
            resolution=resolution,
            negative_prompt=negative_overrides.get(frame.index) or frame_negative_prompt(frame),
            seed=seed,
            generate_audio=generate_audio,
            watermark=watermark,
            # Only remote URLs work as a first frame; local capture paths need
            # uploading first, so they are recorded but not sent.
            image_url=reference if reference.startswith(("http://", "https://")) else None,
        )
        if reference and not reference.startswith(("http://", "https://")):
            result.extra["reference_asset"] = reference
        try:
            result.task_id = vm.submit(req)
            result.state = "running"
            started[frame.index] = time.time()
            report(f"submitted frame {frame.index} ({frame.title or '—'}) → {result.task_id}")
        except VideoGenError as exc:
            result.state = "failed"
            result.error = str(exc)
            logger.error("frame %s submit failed: %s", frame.index, exc)
        results.append(result)

    # ── poll ─────────────────────────────────────────────────────────────────
    pending = [r for r in results if r.state == "running" and r.task_id]
    deadline = time.time() + max_wait
    while pending and time.time() < deadline:
        time.sleep(poll_interval)
        still: list[ClipResult] = []
        for result in pending:
            try:
                status = vm.poll(result.task_id)  # type: ignore[arg-type]
            except VideoGenError as exc:
                result.state, result.error = "failed", str(exc)
                logger.error("frame %s poll failed: %s", result.index, exc)
                continue
            if status.state in ("pending", "running"):
                still.append(result)
                continue
            result.elapsed_seconds = round(time.time() - started.get(result.index, time.time()), 1)
            if status.state == "failed":
                result.state, result.error = "failed", status.error or "task failed"
                logger.error("frame %s failed: %s", result.index, result.error)
                continue
            result.video_url = status.video_url
            dest = out / f"{result.index:02d}-{_slug_for(sb, result.index)}.mp4"
            try:
                vm.download(status, dest)
                result.state, result.video_path = "succeeded", str(dest)
                report(f"frame {result.index} done in {result.elapsed_seconds}s → {dest}")
            except Exception as exc:  # noqa: BLE001 - download/IO surface
                result.state, result.error = "failed", f"download failed: {exc}"
                logger.error("frame %s download failed: %s", result.index, exc)
        pending = still

    for result in pending:
        result.state = "failed"
        result.error = f"timed out after {max_wait}s"

    manifest = out / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "storyboard": str(Path(storyboard_path).resolve()),
                "provider": provider,
                "model": vm.model,
                "resolution": resolution,
                "ratio": target_ratio,
                "clips": [asdict(r) for r in results],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    report(f"manifest: {manifest}")
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
            "vertex: no GCP project id found. Vertex requires a real Google Cloud "
            "project in its resource path (an arbitrary name returns 403 "
            "CONSUMER_INVALID). Set VERTEX_VIDEO_PROJECT in .env, or add "
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
