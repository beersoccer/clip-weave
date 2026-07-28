"""Project Factory — assembles the HF project structure from BRIEF.md."""

import logging
import re
import shutil
from pathlib import Path

from clip_weave.adapters import hyperframes as hf

logger = logging.getLogger(__name__)

# ── Positive preservation (checked before noise filter) ───────────────────────
# Files whose names signal intentional brand design assets — always keep even if
# they would otherwise match a noise pattern.
_LOGO_SIGNALS = re.compile(
    r"(logo|brand|logotype|wordmark|trademark|emblem|crest|symbol|identity)",
    re.IGNORECASE,
)

# ── Confirmed noise ───────────────────────────────────────────────────────────
# Narrow patterns targeting only known-useless file types; does NOT catch
# hash-named raster images, which may be product photos. SVG heuristic:
# webpack bundles hashed names ≥8 hex chars; human-authored SVGs use words.
_CAPTURE_NOISE = re.compile(
    r"(favicon\.ico"
    r"|\.ico$"                              # ICO format = browser tab icons
    r"|wechat[_-]?qrcode"                  # QR codes
    r"|whatsapp"                            # WhatsApp icon
    r"|svg-[0-9a-f]{8,}\.svg$"            # webpack hash-named sprite sheets
    r"|[-_]sprite[-_.]"                    # CSS sprite sheets
    r"|social[-_]icon(?:s)?[-_.]"          # explicit social icon filenames
    r"|loader\.(gif|png|svg)$"             # loading animations
    r")",
    re.IGNORECASE,
)

# Oversized rasters: not crisp brand assets; saves Vision API cost and bandwidth.
# SVG is exempt: brand logos are often tiny vectors (2–20 KB).
# Files matching _LOGO_SIGNALS are also exempt from the size limit.
_MAX_RASTER_BYTES = 1_500_000


def _filter_capture_assets(assets_dir: Path) -> None:
    """Remove noise files from capture/assets/, always preserving brand logos.

    Decision order per file:
      1. Positive signal (logo/brand/wordmark in name) → keep unconditionally
      2. Known noise pattern → remove
      3. SVG → keep (vectors have no meaningful size limit)
      4. Oversized raster (> 1.5 MB) → remove
    """
    if not assets_dir.exists():
        return
    removed: list[str] = []
    for f in sorted(assets_dir.iterdir()):
        if not f.is_file():
            continue

        # Rule 1 — positive preservation: brand identity files are never filtered
        if _LOGO_SIGNALS.search(f.stem):
            continue

        # Rule 2 — confirmed noise patterns
        if _CAPTURE_NOISE.search(f.name):
            f.unlink()
            removed.append(f.name)
            continue

        # Rule 3 — SVG files with human-readable names: keep (vectors can be tiny)
        if f.suffix.lower() == ".svg":
            continue

        # Rule 4 — oversized raster images
        if (
            f.stat().st_size > _MAX_RASTER_BYTES
            and f.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
        ):
            size_kb = f.stat().st_size // 1024
            f.unlink()
            removed.append(f"{f.name} ({size_kb} KB, oversized raster)")

    if removed:
        logger.info("Filtered %d noise/oversized asset(s): %s", len(removed), ", ".join(removed))


def setup(
    project_dir: Path,
    source_url: str | None = None,
    uploaded_files: list[Path] | None = None,
) -> Path:
    """Initialize HF project, run capture if needed, return project_dir."""
    hf.init(project_dir)

    if source_url and "figma.com" not in source_url:
        logger.info("Capturing from URL: %s", source_url)
        hf.capture(source_url, project_dir)
        _filter_capture_assets(project_dir / "capture" / "assets")

    if uploaded_files:
        _stage_uploaded_files(uploaded_files, project_dir)

    if source_url is None and not uploaded_files:
        _synthesize_tokens(project_dir)

    return project_dir


def _stage_uploaded_files(files: list[Path], project_dir: Path) -> None:
    """Copy uploaded files into capture/assets/."""
    assets_dir = project_dir / "capture" / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
        dest = assets_dir / f.name
        shutil.copy2(f, dest)
        logger.info("Staged %s → %s", f.name, dest)
    _synthesize_tokens(project_dir)


def _synthesize_tokens(project_dir: Path) -> None:
    """Write a minimal tokens.json for no-capture or local-file paths."""
    import json
    tokens_path = project_dir / "capture" / "extracted" / "tokens.json"
    if tokens_path.exists():
        return
    tokens_path.parent.mkdir(parents=True, exist_ok=True)

    brief_path = project_dir / "BRIEF.md"
    title = project_dir.name
    description = ""
    if brief_path.exists():
        for line in brief_path.read_text().splitlines():
            if line.startswith("message:"):
                title = line.split(":", 1)[1].strip().strip('"')
            elif line.startswith("## Intent"):
                continue
            elif description == "" and line.strip() and not line.startswith("#"):
                description = line.strip()

    tokens_path.write_text(json.dumps({
        "title": title,
        "description": description,
        "colors": [],
        "fonts": [],
    }, ensure_ascii=False, indent=2))
    logger.info("Synthesized tokens.json at %s", tokens_path)
