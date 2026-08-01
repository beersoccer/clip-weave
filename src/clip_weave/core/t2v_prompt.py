"""STORYBOARD.md → T2V prompts, assembled from HF's own artifacts.

## Prompt anatomy

Every major vendor guide converges on the same ordered slots, so the builder
emits exactly those and nothing else:

    Subject · Action · Scene/Location · Camera framing & motion · Lighting ·
    Style/medium · Audio (when the model generates sound) · Constraints (negative)

Sources (content rephrased for compliance with licensing restrictions):
  * Google DeepMind, "How to create effective prompts with Veo 3" — names shot
    framing and motion, style, lighting, character description, location,
    action, dialogue, and sound design as the dimensions to specify:
    https://deepmind.google/models/veo/prompt-guide/
  * Runway Academy prompting guide — treat prompting as iteration: change one
    variable at a time and re-read the result:
    https://academy.runwayml.com/guides/prompting-guide
  * Alibaba Model Studio text-to-video API reference — `prompt_extend` rewrites
    short prompts, `negative_prompt` carries exclusions:
    https://help.aliyun.com/en/model-studio/text-to-video-api-reference
  * Practical write-ups converge on ~30–200 words per clip, one clear scene and
    one dominant camera move per generation.

## Where each slot comes from (all of it already exists in HF's output)

| Slot | HF source |
|---|---|
| Subject / Action | frame `scene`, `keyMessage`, `narrativeRole` |
| Scene | frame `scene` + the frame's focal asset description |
| Camera | frame narrative's camera verbs + storyboard `Motion grammar` |
| Lighting / Style | storyboard `Palette` + `Motion grammar` (global direction block) |
| Audio | frame `sfx`, and `voiceover` only when explicitly enabled |
| Constraints | storyboard `Negative list` + the standing text/UI exclusions |
| Reference image | frame `focal:` / `asset_candidates` — the Asset Matcher's pick, reused as-is |

Nothing here re-runs asset matching: the storyboard already records the decision.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from clip_weave.core.storyboard import Frame, Storyboard, parse_storyboard

logger = logging.getLogger(__name__)

PROMPTS_FILENAME = "T2V-PROMPTS.md"

# Generative video models render text badly; storyboards are full of on-screen
# copy, so these exclusions are always appended.
_STANDING_NEGATIVE = (
    "on-screen text, captions, subtitles, watermark, logo, UI chrome, "
    "browser window, mouse cursor, distorted characters"
)

# Camera vocabulary that actually appears in HF storyboards, mapped to plain
# cinematography language a video model understands.
_CAMERA_TERMS: list[tuple[str, str]] = [
    (r"lean-?in|push-?in|zoom-?in", "slow dolly-in"),
    (r"pull-?back|zoom-?out|settles? wider", "slow dolly-out"),
    (r"\bpans?\b|pan to|pan across", "steady pan"),
    (r"\btilts?\b", "slow tilt"),
    (r"orbit|arc around", "orbiting arc move"),
    (r"tracking|follows?\b", "tracking shot"),
    (r"static|dead-?static|holds? still|\bhold\b", "locked-off static camera"),
    (r"handheld|shaky", "handheld camera"),
    (r"overhead|top-?down|俯视", "overhead top-down angle"),
    (r"low-?angle", "low angle"),
    (r"close-?up|特写", "close-up"),
    (r"wide shot|全景", "wide shot"),
]

_FILMABLE_HINT = re.compile(
    r"(卡片|card|图表|chart|数据|指标|stat|文字|type|typography|logo|按钮|button|"
    r"pill|grid|网格|计数|count-?up|字幕|caption|弹入|崩入|落入|排版|大字)",
    re.IGNORECASE,
)


@dataclass
class PromptSpec:
    """One clip's prompt, kept as slots so each can be edited independently."""

    index: int
    title: str = ""
    subject: str = ""
    action: str = ""
    scene: str = ""
    camera: str = ""
    lighting_style: str = ""
    audio: str = ""
    negative: str = ""
    duration: int = 5
    ratio: str = "16:9"
    reference: str = ""          # focal asset reused as an i2v first frame
    needs_review: bool = False   # graphics-heavy frame: probably belongs on the HTML path
    notes: str = ""

    def to_prompt(self) -> str:
        """Flatten the slots into the vendor-recommended ordering."""
        ordered = [
            self.subject,
            self.action,
            self.scene,
            self.camera,
            self.lighting_style,
            self.audio,
        ]
        parts = [p.strip().rstrip(".;,。；") for p in ordered if p and p.strip()]
        return ". ".join(parts) + "." if parts else self.title


@dataclass
class PromptDoc:
    globals: dict[str, Any] = field(default_factory=dict)
    specs: list[PromptSpec] = field(default_factory=list)

    def by_index(self) -> dict[int, PromptSpec]:
        return {s.index: s for s in self.specs}


# ── build ─────────────────────────────────────────────────────────────────────

def build_doc(
    sb: Storyboard,
    *,
    provider: str = "",
    model: str = "",
    resolution: str = "1080p",
    include_voiceover: bool = False,
    include_audio: bool = True,
    min_asset_score: float | None = None,
) -> PromptDoc:
    """Assemble a `PromptDoc` from a parsed storyboard."""
    palette = sb.direction_field("Palette")
    motion = sb.direction_field("Motion grammar")
    negative_list = sb.direction_field("Negative list")
    ratio = sb.aspect_ratio()

    lighting_style = _style_line(palette, motion)
    negative = "; ".join(p for p in (negative_list, _STANDING_NEGATIVE) if p)

    specs: list[PromptSpec] = []
    for frame in sb.frames:
        specs.append(
            _build_spec(
                frame,
                sb=sb,
                ratio=ratio,
                lighting_style=lighting_style,
                negative=negative,
                include_voiceover=include_voiceover,
                include_audio=include_audio,
                min_asset_score=min_asset_score,
            )
        )

    return PromptDoc(
        globals={
            "generated_from": sb.path.name,
            "provider": provider,
            "model": model,
            "resolution": resolution,
            "ratio": ratio,
            "style": lighting_style,
            "negative": negative,
        },
        specs=specs,
    )


def _build_spec(
    frame: Frame,
    *,
    sb: Storyboard,
    ratio: str,
    lighting_style: str,
    negative: str,
    include_voiceover: bool,
    include_audio: bool,
    min_asset_score: float | None,
) -> PromptSpec:
    scene_text = frame.scene or (frame.narrative.split("\n\n")[0] if frame.narrative else "")
    subject = frame.meta.get("keyMessage") or frame.meta.get("keymessage") or ""
    action = frame.meta.get("narrativeRole") or frame.meta.get("narrativerole") or ""

    reference, ref_desc = _pick_reference(frame, min_asset_score)

    audio = ""
    if include_audio:
        bits = []
        sfx = frame.meta.get("sfx", "").strip()
        if sfx:
            bits.append(f"Audio: {sfx.replace(',', ',')}")
        if include_voiceover and frame.voiceover:
            bits.append(f'Dialogue: "{frame.voiceover}"')
        audio = ". ".join(bits)

    spec = PromptSpec(
        index=frame.index,
        title=frame.title,
        subject=_clean(subject),
        action=_clean(action),
        scene=_clean(_scene_with_reference(scene_text, ref_desc)),
        camera=_camera_line(frame, sb),
        lighting_style=lighting_style,
        audio=audio,
        negative=negative,
        duration=int(frame.duration_seconds or 5),
        ratio=ratio,
        reference=reference or "",
        needs_review=bool(_FILMABLE_HINT.search(scene_text)),
    )
    if spec.needs_review:
        spec.notes = (
            "graphics/text-heavy frame — video models render type and charts poorly; "
            "consider keeping this frame on the HTML path"
        )
    return spec


def _pick_reference(frame: Frame, min_score: float | None) -> tuple[str | None, str]:
    """Reuse the Asset Matcher's pick recorded in the storyboard.

    Honours a minimum match score when the storyboard carries one: a weak match
    is worse than no reference at all, because the model will faithfully copy an
    irrelevant image.
    """
    focal = frame.focal_asset()
    candidates = frame.asset_candidates()
    best = candidates[0] if candidates else None

    if best and min_score is not None and best.get("score") is not None:
        if float(best["score"]) < min_score:
            logger.info(
                "frame %s: best asset %s scored %.2f < %.2f — no reference image used",
                frame.index,
                best["filename"],
                float(best["score"]),
                min_score,
            )
            return None, ""

    description = best.get("description", "") if best else ""
    return (focal or (best["filename"] if best else None)), description


def _scene_with_reference(scene_text: str, ref_desc: str) -> str:
    if ref_desc and len(ref_desc) > 8:
        return f"{scene_text}. Visual reference: {ref_desc}"
    return scene_text


def _camera_line(frame: Frame, sb: Storyboard) -> str:
    """One dominant camera move per clip — vendor guides warn against stacking moves."""
    haystack = " ".join([frame.narrative, frame.scene, sb.direction_field("Motion grammar")])
    for pattern, phrase in _CAMERA_TERMS:
        if re.search(pattern, haystack, re.IGNORECASE):
            return f"Camera: {phrase}"
    return "Camera: locked-off static camera"


def _style_line(palette: str, motion: str) -> str:
    bits = ["cinematic, photoreal, 24fps, shallow depth of field"]
    colours = re.findall(r"#[0-9a-fA-F]{3,8}", palette)
    if colours:
        bits.append("colour palette " + ", ".join(dict.fromkeys(colours)))
    if "dark" in palette.lower() or "near-black" in palette.lower():
        bits.append("low-key lighting, dark background")
    if motion:
        bits.append("smooth long-tail easing, deliberate pacing")
    return "; ".join(bits)


# GSAP/motion vocabulary that means nothing to a video model, used by the
# PARENTHETICAL pass: whole `(...)`/backtick asides get dropped if they
# CONTAIN any of this vocabulary, so it's safe to include generic-looking
# words here (`stagger`, `scaleX`) — a parenthetical aside in a storyboard is
# reliably implementation jargon, never ordinary prose.
_GSAP_VOCAB_PAREN = (
    r"(?:gsap[\w.\-]*|power\d\.\w+|spring-pop[\w-]*|sine-wave[\w-]*|"
    r"stagger\w*|scaleX\w*|tween\w*)"
)

# Narrower vocabulary for the BARE-TOKEN pass, which deletes a match wherever
# it sits in a sentence, not just inside brackets. Only tokens that are
# unambiguous even out of context belong here: `stagger` and `scaleX` are
# ordinary-looking English/identifier fragments ("actors stagger across the
# stage", "value scaleXform") and must NOT be included, or the pass deletes
# real words/identifier substrings. `tween` is excluded too since it's a
# real (if informal) English word ("the tween demographic").
_GSAP_VOCAB_BARE = r"(?:gsap[\w.\-]*|power\d\.\w+|spring-pop[\w-]*|sine-wave[\w-]*)"


def _clean(text: str) -> str:
    """Strip HF implementation vocabulary that means nothing to a video model.

    Two passes: first delete an entire parenthetical/backtick span that
    CONTAINS the vocabulary (preserves the original "drop the whole aside"
    behavior for `(gsap-effects, spring-pop-entrance)`), then delete any
    remaining bare occurrence of the narrower vocabulary that was never
    bracketed at all (`power3.out` sitting directly in a sentence).

    The bare-token pass is bounded on a non-identifier character rather than
    `\\b` not because `\\b` fails to treat `.`/`-` as boundaries (it does —
    both are non-word characters in Python's `re`), but because we want the
    OPPOSITE: `-` must NOT count as a boundary inside a compound word, so
    that `co-power3.out` or `pre-tween` (jargon fused onto a hyphen prefix)
    are left alone instead of being mangled into `co-` / `pre-`.
    """
    text = re.sub(rf"\([^)]*{_GSAP_VOCAB_PAREN}[^)]*\)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"`[^`]*`", "", text)
    text = re.sub(rf"(?<![\w.\-]){_GSAP_VOCAB_BARE}(?![\w])", "", text, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", text).strip()


# ── T2V-PROMPTS.md round trip ────────────────────────────────────────────────

def render_markdown(doc: PromptDoc) -> str:
    """Serialise to an editable markdown document."""
    lines = ["---"]
    lines.append(yaml.safe_dump(doc.globals, allow_unicode=True, sort_keys=False).strip())
    lines.append("---")
    lines.append("")
    lines.append(
        "> 每帧一段提示词，槽位顺序遵循厂商指南："
        "主体 · 动作 · 场景 · 镜头 · 光线风格 · 音频 · 负面约束。"
    )
    lines.append("> 直接编辑本文件后重跑 `gen-video` 即以本文件为准；"
                 "要从 STORYBOARD.md 重新生成用 `--regenerate-prompts`。")
    lines.append("")

    for spec in doc.specs:
        lines.append(f"## Frame {spec.index} — {spec.title}".rstrip(" —"))
        lines.append(f"- duration: {spec.duration}")
        lines.append(f"- ratio: {spec.ratio}")
        if spec.reference:
            lines.append(f"- reference: {spec.reference}")
        if spec.needs_review:
            lines.append(f"- needs_review: true   # {spec.notes}")
        for slot in ("subject", "action", "scene", "camera", "lighting_style", "audio", "negative"):
            value = getattr(spec, slot)
            if value:
                lines.append(f"- {slot}: {value}")
        lines.append("")
        lines.append("```prompt")
        lines.append(spec.to_prompt())
        lines.append("```")
        lines.append("")

    return "\n".join(lines)


_FRAME_HEAD = re.compile(r"^##\s*Frame\s*(\d+)\s*(?:[—–\-:]\s*(.*))?$", re.IGNORECASE)
_SLOT = re.compile(r"^[-*]\s*([a-z_]+)\s*:\s*(.*)$", re.IGNORECASE)


def parse_markdown(path: str | Path) -> PromptDoc:
    """Read back an edited `T2V-PROMPTS.md`.

    A fenced ```prompt block, when present, wins over the individual slots —
    that is the escape hatch for hand-written prompts.
    """
    text = Path(path).read_text(encoding="utf-8")
    doc = PromptDoc()

    body = text
    if text.lstrip().startswith("---"):
        stripped = text.lstrip()
        end = stripped.find("\n---", 3)
        if end != -1:
            try:
                loaded = yaml.safe_load(stripped[3:end]) or {}
                if isinstance(loaded, dict):
                    doc.globals = loaded
            except yaml.YAMLError:
                pass
            body = stripped[end + 4 :]

    current: PromptSpec | None = None
    in_prompt = False
    prompt_lines: list[str] = []

    def close() -> None:
        nonlocal current, in_prompt, prompt_lines
        if current is not None:
            if prompt_lines:
                current.notes = current.notes  # keep note
                current.__dict__["_literal_prompt"] = "\n".join(prompt_lines).strip()
            doc.specs.append(current)
        current, in_prompt, prompt_lines = None, False, []

    for line in body.splitlines():
        head = _FRAME_HEAD.match(line.strip())
        if head:
            close()
            current = PromptSpec(index=int(head.group(1)), title=(head.group(2) or "").strip())
            continue
        if current is None:
            continue
        if line.strip().startswith("```"):
            in_prompt = line.strip().lower().startswith("```prompt")
            continue
        if in_prompt:
            prompt_lines.append(line)
            continue
        slot = _SLOT.match(line.strip())
        if not slot:
            continue
        key, value = slot.group(1).lower(), slot.group(2).split("#")[0].strip()
        if key == "duration":
            try:
                current.duration = int(float(value))
            except ValueError:
                pass
        elif key == "needs_review":
            current.needs_review = value.strip().lower() in ("true", "yes", "1")
        elif key in {"ratio", "reference", "subject", "action", "scene", "camera",
                     "lighting_style", "audio", "negative", "title"}:
            setattr(current, key, value)

    close()
    return doc


def literal_prompt(spec: PromptSpec) -> str:
    """The hand-edited ```prompt block if the file had one, else the assembled slots."""
    return spec.__dict__.get("_literal_prompt") or spec.to_prompt()


def load_or_create(
    storyboard_path: str | Path,
    *,
    regenerate: bool = False,
    **build_kwargs: Any,
) -> tuple[PromptDoc, Path, bool]:
    """Return `(doc, path, created)` — the round trip that makes prompts editable."""
    sb_path = Path(storyboard_path)
    prompts_path = sb_path.parent / PROMPTS_FILENAME

    if prompts_path.exists() and not regenerate:
        doc = parse_markdown(prompts_path)
        if doc.specs:
            return doc, prompts_path, False
        logger.warning("%s has no frames — regenerating from %s", prompts_path.name, sb_path.name)

    sb = parse_storyboard(sb_path)
    doc = build_doc(sb, **build_kwargs)
    prompts_path.write_text(render_markdown(doc), encoding="utf-8")
    return doc, prompts_path, True


__all__ = [
    "PROMPTS_FILENAME",
    "PromptDoc",
    "PromptSpec",
    "build_doc",
    "literal_prompt",
    "load_or_create",
    "parse_markdown",
    "render_markdown",
    "asdict",
]
