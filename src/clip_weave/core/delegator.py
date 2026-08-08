"""Delegator — hands off to HF workflow skill after BRIEF.md is ready.

In automated pipeline mode this prints the instruction a human or
orchestrating agent should pass to Claude Code.  In an agent context,
the caller (Claude itself) reads BRIEF.md and invokes /<workflow-name>.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def build_delegation_prompt(project_dir: Path) -> str:
    """Return the prompt for the project-selected production path."""
    brief_path = project_dir / "BRIEF.md"
    if not brief_path.exists():
        raise FileNotFoundError(f"BRIEF.md not found at {brief_path}")

    from clip_weave.core import render_path as rp

    profile, _ = rp.resolve(project_dir)
    if profile == "t2v_brand_film":
        return (
            f"Prepare and review `{project_dir / 'STORYBOARD.md'}` for the T2V brand-film project at "
            f"`{project_dir}`. Do not add frame-level render fields. Then run "
            f"`uv run python -m clip_weave gen-video {project_dir / 'STORYBOARD.md'} "
            "--provider doubao --prompts-only` before any paid generation."
        )

    workflow = _read_workflow(brief_path)
    return (
        f"Please run `/{workflow}` for the project at `{project_dir}`. "
        f"BRIEF.md is already written at `{brief_path}` — "
        "read it first (as the HyperFrames skill requires) then execute the full workflow."
    )


def print_delegation_instructions(project_dir: Path) -> None:
    """Print human-readable handoff instructions to stdout."""
    brief_path = project_dir / "BRIEF.md"
    from clip_weave.core import render_path as rp

    profile, _ = rp.resolve(project_dir)
    if profile == "t2v_brand_film":
        print(f"\n{'='*60}")
        print("clip-weave: T2V brand-film project ready")
        print(f"{'='*60}")
        print(f"  Project dir : {project_dir}")
        print(f"  Profile     : {profile}")
        print(f"  BRIEF.md    : {brief_path}")
        print("\nNext step:")
        print(f"  {build_delegation_prompt(project_dir)}")
        print(f"{'='*60}\n")
        return

    workflow = _read_workflow(brief_path)
    project_name = project_dir.name

    print(f"\n{'='*60}")
    print(f"clip-weave: project ready — delegating to HyperFrames")
    print(f"{'='*60}")
    print(f"  Project dir : {project_dir}")
    print(f"  Workflow    : /{workflow}")
    print(f"  BRIEF.md    : {brief_path}")
    print(f"\nNext step: in Claude Code, run:")
    print(f"  /{workflow}")
    print(f"\nOr pass this prompt to Claude:")
    print(f"  {build_delegation_prompt(project_dir)}")
    print(f"{'='*60}\n")


def _read_workflow(brief_path: Path) -> str:
    for line in brief_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("workflow:"):
            return stripped.split(":", 1)[1].strip()
    return "general-video"
