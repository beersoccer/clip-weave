"""Resolve the GCP project id that Vertex requires in its resource path.

Vertex's `predictLongRunning` path is
`projects/{project}/locations/{location}/publishers/google/models/{model}`,
and `{project}` must be a **real Google Cloud project** the gateway's service
account is allowed to bill against. It is an identity, not a label — an
arbitrary name (we tried `projects/-`) comes back as
`403 PERMISSION_DENIED / CONSUMER_INVALID`. So it cannot be invented per video.

What we can do is stop asking for it on every run. Resolution order:

1. ``VERTEX_VIDEO_PROJECT`` env var
2. ``GOOGLE_CLOUD_PROJECT`` / ``GCLOUD_PROJECT`` env var (the Google SDK convention)
3. the storyboard's own frontmatter, or its sibling ``BRIEF.md`` — keys
   ``vertex_project`` / ``gcp_project`` / ``google_cloud_project`` / ``project_id``
4. the local gcloud config (``gcloud config get-value project``)

Set it once (in `.env` for the team, or in `BRIEF.md` when one video bills to a
different project) and no CLI flag is ever needed.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_FRONTMATTER_KEYS = (
    "vertex_project",
    "gcp_project",
    "google_cloud_project",
    "project_id",
)

# GCP project ids: 6–30 chars, lowercase letters/digits/hyphens, letter first.
_VALID = re.compile(r"^[a-z][a-z0-9\-]{4,28}[a-z0-9]$")


def resolve_project(storyboard: str | Path | None = None) -> tuple[str | None, str]:
    """Return `(project_id, where_it_came_from)`; project is None if unknown."""
    for var in ("VERTEX_VIDEO_PROJECT", "GOOGLE_CLOUD_PROJECT", "GCLOUD_PROJECT"):
        value = (os.getenv(var) or "").strip()
        if value:
            return value, f"env {var}"

    if storyboard:
        sb_path = Path(storyboard)
        for candidate in (sb_path, sb_path.parent / "BRIEF.md", sb_path.parent / "brief.md"):
            found = _from_frontmatter(candidate)
            if found:
                key, value = found
                return value, f"{candidate.name}:{key}"

    from_gcloud = _from_gcloud()
    if from_gcloud:
        return from_gcloud, "gcloud config"

    return None, "unresolved"


def _from_frontmatter(path: Path) -> tuple[str, str] | None:
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    # Only scan the frontmatter block (or the first 60 lines if there is none).
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        try:
            end = lines[1:].index("---") + 1
        except ValueError:
            end = min(len(lines), 60)
        lines = lines[1:end]
    else:
        lines = lines[:60]

    for line in lines:
        m = re.match(r"\s*(?:[-*]\s*)?([A-Za-z_][\w]*)\s*:\s*(.+)$", line)
        if not m:
            continue
        key = m.group(1).lower()
        if key in _FRONTMATTER_KEYS:
            value = m.group(2).strip().strip('"').strip("'")
            if value:
                return key, value
    return None


def _from_gcloud() -> str | None:
    exe = shutil.which("gcloud")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "config", "get-value", "project"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = (out.stdout or "").strip()
    if not value or value in ("(unset)", "unset"):
        return None
    return value


def looks_like_project_id(value: str) -> bool:
    """Cheap sanity check so a video project name is not mistaken for a GCP id."""
    return bool(_VALID.match(value))


__all__ = ["looks_like_project_id", "resolve_project"]
