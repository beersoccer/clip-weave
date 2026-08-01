"""STORYBOARD.md parser + video-model prompt builder.

Mirrors the HyperFrames storyboard base format (see
`.agents/skills/hyperframes-core/references/storyboard-format.md`):

    ---
    format: 1920x1080
    duration: 47s
    message: "..."
    ---

    ## Frame 1 — Title
    - scene: one-line description
    - voiceover: "..."
    - duration: 5.851s
    - ...

    free-form narrative until the next heading

The parser is lenient by design: it never raises on unexpected content, it
collects anything it does not recognise into ``extra`` / ``warnings``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# `## Frame 1 — Title` / `### Beat 2: Title` / `## Scene 3`
_HEADING_RE = re.compile(
    r"^#{2,3}\s*(?:Frame|Beat|Scene)\s*(\d+)?\s*(?:[—–\-:.)]\s*)?(.*)$",
    re.IGNORECASE,
)
# `- key: value` metadata bullet
_BULLET_RE = re.compile(r"^[-*]\s+([A-Za-z_][\w \-]*?)\s*:\s*(.*)$")
# bare `key: value` line (the storyboards also use narrativeRole:, keyMessage:, …)
_BARE_KV_RE = re.compile(r"^([A-Za-z_][\w\-]*)\s*:\s*(.+)$")

# Metadata keys that describe *how the HTML frame animates*. They are noise for
# a generative video model, so they are kept out of the built prompt.
_MOTION_KEYS = {
    "blueprint",
    "src",
    "status",
    "poster",
    "sfx",
    "roles",
    "focal",
    "asset_candidates",
    "transition_in",
    "transition",
}

_ALIASES = {
    "description": "scene",
    "summary": "scene",
    "caption": "scene",
    "vo": "voiceover",
    "voice_over": "voiceover",
    "narration": "voiceover",
    "transition": "transition_in",
}


@dataclass
class Frame:
    index: int  # 1-based position in the file
    number: int | None  # the number written in the heading, if any
    title: str
    meta: dict[str, str] = field(default_factory=dict)
    narrative: str = ""

    @property
    def scene(self) -> str:
        return self.meta.get("scene", "")

    @property
    def voiceover(self) -> str:
        return self.meta.get("voiceover", "").strip().strip('"').strip("“”")

    @property
    def duration_seconds(self) -> float | None:
        return _parse_duration(self.meta.get("duration"))

    def slug(self) -> str:
        base = self.title or self.scene or f"frame-{self.index}"
        slug = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "-", base).strip("-").lower()
        return (slug or f"frame-{self.index}")[:40]


@dataclass
class Storyboard:
    path: Path
    globals: dict[str, Any] = field(default_factory=dict)
    frames: list[Frame] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def format(self) -> str:
        return str(self.globals.get("format", "") or "")

    @property
    def message(self) -> str:
        return str(self.globals.get("message", "") or "")

    def aspect_ratio(self) -> str:
        """`1920x1080` → `16:9`. Defaults to 16:9 when unparseable."""
        m = re.match(r"\s*(\d+)\s*[x×*]\s*(\d+)\s*", self.format)
        if not m:
            return "16:9"
        w, h = int(m.group(1)), int(m.group(2))
        if not w or not h:
            return "16:9"
        ratio = w / h
        table = {
            "16:9": 16 / 9,
            "9:16": 9 / 16,
            "1:1": 1.0,
            "4:3": 4 / 3,
            "3:4": 3 / 4,
            "21:9": 21 / 9,
        }
        return min(table, key=lambda k: abs(table[k] - ratio))


def parse_storyboard(path: str | Path) -> Storyboard:
    """Parse a STORYBOARD.md file into a `Storyboard`."""
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    sb = Storyboard(path=p)

    body = text
    if text.lstrip().startswith("---"):
        stripped = text.lstrip()
        end = stripped.find("\n---", 3)
        if end != -1:
            raw_fm = stripped[3:end]
            body = stripped[end + 4 :]
            try:
                loaded = yaml.safe_load(raw_fm) or {}
                if isinstance(loaded, dict):
                    sb.globals = loaded
                else:
                    sb.warnings.append("frontmatter is not a mapping — ignored")
            except yaml.YAMLError as exc:  # pragma: no cover - defensive
                sb.warnings.append(f"frontmatter YAML error: {exc}")

    current: Frame | None = None
    narrative_lines: list[str] = []
    in_meta = True

    def close() -> None:
        nonlocal current, narrative_lines
        if current is not None:
            current.narrative = "\n".join(narrative_lines).strip()
            sb.frames.append(current)
        current, narrative_lines = None, []

    for line in body.splitlines():
        stripped = line.strip()
        heading = _HEADING_RE.match(stripped) if stripped.startswith("#") else None
        if heading:
            close()
            number = int(heading.group(1)) if heading.group(1) else None
            current = Frame(
                index=len(sb.frames) + 1,
                number=number,
                title=heading.group(2).strip(),
            )
            in_meta = True
            continue

        if stripped.startswith("#"):  # a non-frame heading ends the current frame
            close()
            in_meta = True
            continue

        if current is None:
            continue

        bullet = _BULLET_RE.match(stripped)
        if bullet and in_meta:
            key = _norm_key(bullet.group(1))
            current.meta[key] = bullet.group(2).strip()
            continue

        if not stripped:
            if narrative_lines:
                narrative_lines.append("")
            continue

        in_meta = False
        bare = _BARE_KV_RE.match(stripped)
        if bare and " " not in bare.group(1):
            key = _norm_key(bare.group(1))
            if key not in current.meta:
                current.meta[key] = bare.group(2).strip()
                continue
        narrative_lines.append(line.rstrip())

    close()

    if not sb.frames:
        sb.warnings.append("no `## Frame N` sections found")
    return sb


def _norm_key(key: str) -> str:
    k = key.strip().replace(" ", "_")
    lowered = k.lower()
    return _ALIASES.get(lowered, lowered if lowered in _KNOWN else k)


_KNOWN = {
    "scene",
    "voiceover",
    "duration",
    "transition_in",
    "status",
    "src",
    "type",
    "poster",
    "beat",
    "blueprint",
    "persuasion",
    "asset_candidates",
    "focal",
    "roles",
    "sfx",
    "negative_prompt",
}


def _parse_duration(value: str | None) -> float | None:
    if not value:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)", str(value))
    return float(m.group(1)) if m else None


def build_prompt(
    sb: Storyboard,
    frame: Frame,
    *,
    include_voiceover: bool = False,
    style: str | None = None,
) -> str:
    """Turn one storyboard frame into a single text-to-video prompt.

    Motion-implementation metadata (`blueprint`, `roles`, `sfx`, `src`, GSAP
    scene beats) is deliberately dropped — it describes an HTML composition,
    not a filmed shot. What survives: the shot description, the narrative
    intent, the key message, plus global style direction.
    """
    parts: list[str] = []

    if frame.scene:
        parts.append(frame.scene)
    elif frame.narrative:
        parts.append(frame.narrative.split("\n\n")[0])

    for key in ("narrativeRole", "narrativerole", "keyMessage", "keymessage"):
        val = frame.meta.get(key)
        if val:
            parts.append(val)

    beat = frame.meta.get("beat")
    if beat:
        parts.append(f"情绪基调 / mood: {beat}")

    if include_voiceover and frame.voiceover:
        parts.append(f"旁白 / voiceover: {frame.voiceover}")

    if style:
        parts.append(style)
    elif sb.message:
        parts.append(f"整体主题 / overall theme: {sb.message}")

    # Drop motion keys if they leaked into `parts` via the narrative fallback.
    prompt = "。".join(p.strip().rstrip("。.") for p in parts if p and p.strip())
    return prompt.strip() + "。" if prompt else (frame.title or "video shot")


def frame_negative_prompt(frame: Frame) -> str | None:
    return frame.meta.get("negative_prompt") or None


__all__ = [
    "Frame",
    "Storyboard",
    "build_prompt",
    "frame_negative_prompt",
    "parse_storyboard",
]
