"""Project Factory — assembles the HF project structure from BRIEF.md."""

import logging
import shutil
from pathlib import Path

from clip_weave.adapters import hyperframes as hf

logger = logging.getLogger(__name__)


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
