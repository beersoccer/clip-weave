"""clip-weave CLI — intent → HF workflow delegation."""

import logging
import sys
from pathlib import Path

import click

from clip_weave.config import load_config
from clip_weave.pipeline import run as pipeline_run, guard as pipeline_guard


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )


@click.group()
def cli():
    _setup_logging()


@cli.command("run")
@click.option("--url", default=None, help="Website URL to capture")
@click.option("--message", required=True, help="Core message (one sentence)")
@click.option("--project", default=None, help="Project name (default: derived from URL/message)")
@click.option("--videos-dir", default="videos", help="Root directory for video projects")
@click.option("--length", default="30s", help="Video length (e.g. 15s, 30s, 60s)")
@click.option("--workflow", default=None, help="Force a specific HF workflow")
def run_cmd(url, message, project, videos_dir, length, workflow):
    """Route a video request and prepare the HF project for delegation."""
    cfg = load_config()
    project_name = project or _derive_project_name(url, message)
    user_input = f"{message} {url or ''}".strip()
    if workflow:
        user_input = f"{workflow} {user_input}"

    project_dir = pipeline_run(
        user_input=user_input,
        project_name=project_name,
        videos_dir=Path(videos_dir),
        message=message,
        length=length,
        cfg=cfg,
    )
    click.echo(f"Project ready: {project_dir}")


@cli.command("guard")
@click.argument("project_dir")
def guard_cmd(project_dir):
    """Run Rule Guard pre-flight on compositions in PROJECT_DIR."""
    p = Path(project_dir)
    compositions_dir = p / "compositions"
    if not compositions_dir.exists():
        click.echo(f"No compositions/ directory found in {p}", err=True)
        sys.exit(1)
    ok = pipeline_guard(compositions_dir, project_dir=p)
    if ok:
        click.echo("Rule Guard: all clear")
    else:
        click.echo("Rule Guard: violations need attention — see log above", err=True)
        sys.exit(1)


@cli.command("match-assets")
@click.argument("project_dir")
@click.option("--query", default=None, help="Override query text (default: BRIEF.md message)")
def match_assets_cmd(project_dir, query):
    """Run Asset Matcher on PROJECT_DIR capture/ assets."""
    from clip_weave.adapters.asset_matcher import match_assets
    p = Path(project_dir)
    if not query:
        brief = p / "BRIEF.md"
        query = p.name
        if brief.exists():
            for line in brief.read_text().splitlines():
                if line.startswith("message:"):
                    query = line.split(":", 1)[1].strip().strip('"')
                    break
    results = match_assets(p, [query])
    if results and results[0]:
        click.echo(f"Top {len(results[0])} asset candidates for: {query!r}")
        for i, asset in enumerate(results[0], 1):
            click.echo(f"  {i}. {asset['filename']}")
            click.echo(f"     {asset['description'][:100]}…")
    else:
        click.echo("No asset candidates found (check capture/extracted/asset-descriptions.md)")


def _derive_project_name(url: str | None, message: str) -> str:
    import re
    if url:
        # e.g. https://xiaomiev.com/su7 → xiaomiev-su7
        clean = re.sub(r"https?://", "", url).rstrip("/")
        return re.sub(r"[^a-z0-9]+", "-", clean.lower())[:40]
    return re.sub(r"[^a-z0-9]+", "-", message.lower())[:30]


cli.add_command(run_cmd, name="run")
cli.add_command(guard_cmd, name="guard")
cli.add_command(match_assets_cmd, name="match-assets")

if __name__ == "__main__":
    cli()
