"""HyperFrames CLI adapter — wraps npx hyperframes commands."""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_TIMEOUT_INIT = 60
_TIMEOUT_CAPTURE = 180
_TIMEOUT_CHECK = 60
_TIMEOUT_RENDER = 600


class HyperFramesError(Exception):
    pass


def _run(cmd: list[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess:
    logger.info("HF: %s (cwd=%s)", " ".join(cmd), cwd)
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(cwd),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise HyperFramesError(f"Timed out after {timeout}s: {' '.join(cmd)}")
    if result.returncode != 0:
        raise HyperFramesError(
            f"Exit {result.returncode}: {' '.join(cmd)}\n{result.stderr.strip()}"
        )
    return result


def init(project_dir: Path) -> None:
    """npx hyperframes init <dir> --non-interactive --example=blank"""
    project_dir.mkdir(parents=True, exist_ok=True)
    if (project_dir / "hyperframes.json").exists():
        return
    _run(
        ["npx", "hyperframes", "init", str(project_dir), "--non-interactive", "--example=blank"],
        cwd=project_dir.parent,
        timeout=_TIMEOUT_INIT,
    )


def capture(url: str, project_dir: Path) -> Path:
    """npx hyperframes capture <url> — writes to capture/"""
    capture_dir = project_dir / "capture"
    _run(
        ["npx", "hyperframes", "capture", url, "-o", str(capture_dir)],
        cwd=project_dir,
        timeout=_TIMEOUT_CAPTURE,
    )
    return capture_dir


def lint(project_dir: Path, file: Path | None = None) -> tuple[bool, str]:
    """npx hyperframes lint [file] — returns (ok, output)"""
    cmd = ["npx", "hyperframes", "lint"]
    if file:
        cmd.append(str(file.relative_to(project_dir)))
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(project_dir),
            timeout=30,
        )
        return result.returncode == 0, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return False, "lint timed out"


# `npx hyperframes check <file>` passes an explicit lint entry. HF then treats
# that file as the ROOT composition: packages/lint/src/project.ts:165 skips the
# compositions/ walk and never sets `isSubComposition`, which silently disables
# `media_in_subcomposition` (media.ts:349 returns early without it) along with
# every project-level check (missing/empty sub-composition, duplicate
# composition ids, duplicate audio tracks, missing local assets, HEVC notes).
# Fast to iterate with, but not a substitute for a full pass.
_SINGLE_FILE_COVERAGE_WARNING = (
    "check(file=…) runs HF lint with an explicit entry: media_in_subcomposition "
    "and all project-level checks are skipped. Use it for iteration only — run "
    "check_full() before render."
)


def check(project_dir: Path, file: Path | None = None) -> tuple[bool, str]:
    """npx hyperframes check [file] — returns (ok, output). 10-30s per call.

    Passing `file` narrows the run and loses coverage; see
    `_SINGLE_FILE_COVERAGE_WARNING`. Prefer `check_full()` before rendering.
    """
    cmd = ["npx", "hyperframes", "check"]
    if file:
        logger.warning("%s", _SINGLE_FILE_COVERAGE_WARNING)
        cmd.append(str(file.relative_to(project_dir)))
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(project_dir),
            timeout=_TIMEOUT_CHECK,
        )
        return result.returncode == 0, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return False, f"check timed out after {_TIMEOUT_CHECK}s"


def check_full(project_dir: Path) -> tuple[bool, str]:
    """Full-project `npx hyperframes check` — the only pass with full coverage.

    Exists so callers can state the intent explicitly; a bare `check(dir)` is
    equivalent but reads as if a narrowed run would do.
    """
    return check(project_dir)


def render(project_dir: Path, output: Path | None = None, quality: str = "high") -> Path:
    """npx hyperframes render -- returns path to output video."""
    out = output or (project_dir / "renders" / "video.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    _run(
        ["npx", "hyperframes", "render", "-q", quality, "-o", str(out)],
        cwd=project_dir,
        timeout=_TIMEOUT_RENDER,
    )
    return out
