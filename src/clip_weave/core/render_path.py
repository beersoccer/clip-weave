"""Which renderer a video (or a single frame) goes through: HTML or T2V.

The choice is the user's, never inferred silently:

  * project level — `render: html | t2v | mixed` in `BRIEF.md` frontmatter
  * frame level   — `visual_type: motion | live_action` in `STORYBOARD.md`
                    (`motion` → HTML, `live_action` → T2V)

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

RenderPath = Literal["html", "t2v", "mixed"]
VALID: tuple[str, ...] = ("html", "t2v", "mixed")

DEFAULT: RenderPath = "html"

_RENDER_LINE = re.compile(r"^(render|render_path)\s*:\s*(\S+)\s*$", re.MULTILINE | re.IGNORECASE)

_FRAME_HTML = ("motion", "html", "graphic", "graphics")
_FRAME_T2V = ("live_action", "live-action", "t2v", "footage", "realistic")


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
    """Per-frame override via `visual_type:`, else the project default."""
    value = (frame_meta.get("visual_type") or frame_meta.get("visualtype") or "").strip().lower()
    if value in _FRAME_T2V:
        return "t2v"
    if value in _FRAME_HTML:
        return "html"
    return "t2v" if project_default == "t2v" else "html"


def _frontmatter(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if not text.lstrip().startswith("---"):
        return text[:2000]
    stripped = text.lstrip()
    end = stripped.find("\n---", 3)
    return stripped[3:end] if end != -1 else stripped[:2000]


__all__ = ["DEFAULT", "RenderPath", "VALID", "frame_path", "persist", "resolve"]
