"""Project-level Production Profile selection.

Each project owns exactly one profile. ``html_launch`` produces the complete
video through HyperFrames; ``t2v_brand_film`` owns the generated-video path.
Frame-level renderer fields are forbidden: mixed composition is intentionally
outside the current product boundary.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

ProductionProfile = Literal["html_launch", "t2v_brand_film"]
Engine = Literal["html", "t2v"]

PROFILES: tuple[ProductionProfile, ...] = ("html_launch", "t2v_brand_film")
DEFAULT: ProductionProfile = "html_launch"

_PROFILE_LINE = re.compile(r"^production_profile\s*:\s*(\S+)(?:\s+#.*)?\s*$", re.IGNORECASE)
_LEGACY_RENDER_LINE = re.compile(r"^(render|render_path)\s*:\s*(\S+)(?:\s+#.*)?\s*$", re.IGNORECASE)
_LEGACY_TO_PROFILE: dict[str, ProductionProfile] = {
    "html": "html_launch",
    "t2v": "t2v_brand_film",
}
_ENGINE_BY_PROFILE: dict[ProductionProfile, Engine] = {
    "html_launch": "html",
    "t2v_brand_film": "t2v",
}


class ProfileError(ValueError):
    """Raised when a project or storyboard violates profile boundaries."""


def engine(profile: ProductionProfile) -> Engine:
    """Return the single production engine selected by ``profile``."""
    return _ENGINE_BY_PROFILE[profile]


def resolve(project_dir: str | Path) -> tuple[ProductionProfile | None, str]:
    """Return ``(profile, source)`` from a project's BRIEF frontmatter.

    Old project-level ``render: html|t2v`` values remain readable to make an
    existing project actionable, but every new write migrates them to the
    canonical ``production_profile`` field.
    """
    directory = Path(project_dir)
    for brief in _brief_files(directory):
        name = brief.name
        frontmatter = _frontmatter(brief)

        profile = _find_profile(frontmatter)
        if profile is not None:
            return profile, f"{name}:production_profile"
        if _has_profile_field(frontmatter):
            return None, "unset"

        legacy = _find_legacy_profile(frontmatter)
        if legacy is not None:
            profile, field = legacy
            logger.warning(
                "%s uses legacy render routing; run/project creation will migrate it to production_profile",
                name,
            )
            return profile, f"{name}:{field}"
    return None, "unset"


def persist(project_dir: str | Path, profile: ProductionProfile) -> bool:
    """Persist exactly one canonical profile in ``BRIEF.md``.

    The operation preserves all unrelated frontmatter and prose while removing
    any legacy project-level render keys.
    """
    briefs = _brief_files(Path(project_dir))
    if not briefs:
        return False
    brief = briefs[0]
    if profile not in PROFILES:
        raise ProfileError(f"unknown production profile: {profile!r}")

    text = brief.read_text(encoding="utf-8")
    brief.write_text(_with_profile(text, profile), encoding="utf-8")
    return True


def validate_frames(frame_meta: Iterable[Mapping[str, str]]) -> None:
    """Reject the removed frame-level renderer vocabulary.

    A visible failure is safer than silently ignoring a frame's old intent and
    generating a project through the wrong production path.
    """
    bad_frames = [
        str(index)
        for index, meta in enumerate(frame_meta, start=1)
        if any(str(key).casefold() in {"render", "render_path"} for key in meta)
    ]
    if bad_frames:
        raise ProfileError(
            "frame-level render directives are no longer supported; "
            f"choose one production_profile for the project (frames: {', '.join(bad_frames)})"
        )


def _find_profile(frontmatter: str) -> ProductionProfile | None:
    for line in frontmatter.splitlines():
        match = _PROFILE_LINE.match(line.strip())
        if not match:
            continue
        value = _normalise(match.group(1))
        if value in PROFILES:
            return value  # type: ignore[return-value]
        logger.warning("BRIEF.md has production_profile: %r — expected one of %s", value, ", ".join(PROFILES))
        return None
    return None


def _has_profile_field(frontmatter: str) -> bool:
    return any(_PROFILE_LINE.match(line.strip()) for line in frontmatter.splitlines())


def _find_legacy_profile(frontmatter: str) -> tuple[ProductionProfile, str] | None:
    for line in frontmatter.splitlines():
        match = _LEGACY_RENDER_LINE.match(line.strip())
        if not match:
            continue
        value = _normalise(match.group(2))
        profile = _LEGACY_TO_PROFILE.get(value)
        if profile is not None:
            return profile, match.group(1).lower()
        logger.warning("BRIEF.md has legacy render: %r — expected html or t2v", value)
        return None
    return None


def _brief_files(directory: Path) -> list[Path]:
    """Return existing BRIEF files in canonical precedence order.

    Resolve their directory entries rather than synthesising ``BRIEF.md`` paths:
    on a case-insensitive filesystem that preserves the original ``brief.md``
    spelling, the resolved path must still retain that spelling so a legacy file
    is migrated in place and diagnostics name the real source.
    """
    if not directory.is_dir():
        return []
    entries = {path.name: path for path in directory.iterdir() if path.is_file()}
    return [entries[name] for name in ("BRIEF.md", "brief.md") if name in entries]


def _normalise(value: str) -> str:
    return value.strip().strip('"').strip("'").lower()


def _with_profile(text: str, profile: ProductionProfile) -> str:
    lines = text.splitlines(keepends=True)
    if lines and lines[0].strip() == "---":
        closing = next((i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---"), None)
        if closing is not None:
            retained = [
                line
                for line in lines[1:closing]
                if not _PROFILE_LINE.match(line.strip()) and not _LEGACY_RENDER_LINE.match(line.strip())
            ]
            return "---\n" + f"production_profile: {profile}\n" + "".join(retained) + "---\n" + "".join(lines[closing + 1:])
    return f"---\nproduction_profile: {profile}\n---\n\n{text}"


def _frontmatter(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[1:index])
    return "\n".join(lines[1:])


__all__ = [
    "DEFAULT",
    "Engine",
    "PROFILES",
    "ProductionProfile",
    "ProfileError",
    "engine",
    "persist",
    "resolve",
    "validate_frames",
]
