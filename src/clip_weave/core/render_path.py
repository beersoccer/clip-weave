"""Which renderer a video (or a single frame) goes through: HTML or T2V.

The choice is the user's, never inferred silently, and it uses one vocabulary
(`html` | `t2v`) at both levels:

  * project level — `render: html | t2v` in `BRIEF.md` frontmatter
  * frame level   — `render: html | t2v` on a `STORYBOARD.md` frame, overriding
                    the project default for that one frame

There is no `mixed` project value. Mixing is expressed by annotating the
individual frames that should NOT follow the project default — the project
default is still a single html-or-t2v choice, just one that some frames opt out
of. A frame without a `render:` line follows the project default.

When neither says anything, callers ask once and persist the answer to BRIEF.md,
so the question is asked at most once per project.

HTML is the default because it is deterministic, free of inference cost, and the
only path that renders precise type, brand colour and data correctly. T2V is the
opt-in for footage-like shots that HTML cannot produce.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

RenderPath = Literal["html", "t2v"]
VALID: tuple[str, ...] = ("html", "t2v")

DEFAULT: RenderPath = "html"

_RENDER_LINE = re.compile(r"^(render|render_path)\s*:\s*(\S+)\s*$", re.MULTILINE | re.IGNORECASE)


def resolve(project_dir: str | Path) -> tuple[RenderPath | None, str]:
    """Return `(path, source)`; path is None when the user has not chosen yet."""
    d = Path(project_dir)
    for name in ("BRIEF.md", "brief.md"):
        brief = d / name
        if not brief.is_file():
            continue
        m = _RENDER_LINE.search(_frontmatter(brief))
        if m:
            value = m.group(2).strip().strip('"').lower()
            if value in VALID:
                return value, f"{name}:{m.group(1)}"
            logger.warning("%s has render: %r — expected one of %s", name, value, ", ".join(VALID))
    return None, "unset"


def persist(project_dir: str | Path, path: RenderPath) -> bool:
    """Write `render:` into BRIEF.md frontmatter. Returns False if there is no BRIEF."""
    brief = Path(project_dir) / "BRIEF.md"
    if not brief.is_file():
        return False
    text = brief.read_text(encoding="utf-8")
    if _RENDER_LINE.search(_frontmatter(brief)):
        text = _RENDER_LINE.sub(f"render: {path}", text, count=1)
    elif text.lstrip().startswith("---"):
        head, sep, rest = text.partition("\n")
        text = f"{head}{sep}render: {path}\n{rest}"
    else:
        text = f"---\nrender: {path}\n---\n\n{text}"
    brief.write_text(text, encoding="utf-8")
    return True


def frame_path(frame_meta: dict[str, str], project_default: RenderPath) -> RenderPath:
    """Per-frame override via `render:` on the frame, else the project default.

    Uses the same `html | t2v` vocabulary as the project-level `render:` in
    BRIEF.md — one word, one meaning, at both levels. An unrecognised or
    missing value falls back to the project default rather than being read as
    an implicit choice.
    """
    value = (frame_meta.get("render") or frame_meta.get("render_path") or "").strip().lower()
    if value in VALID:
        return value  # type: ignore[return-value]
    return project_default


def _frontmatter(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if not text.lstrip().startswith("---"):
        return text[:2000]
    stripped = text.lstrip()
    end = stripped.find("\n---", 3)
    return stripped[3:end] if end != -1 else stripped[:2000]


__all__ = ["DEFAULT", "RenderPath", "VALID", "frame_path", "persist", "resolve"]
