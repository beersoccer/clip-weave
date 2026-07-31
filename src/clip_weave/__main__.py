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


@cli.command("gen-video")
@click.argument("storyboard", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--provider",
    type=click.Choice(["doubao", "ali", "vertex"]),
    required=True,
    help="Gateway video model: doubao (Seedance) | ali (Wan) | vertex (Veo)",
)
@click.option("--out-dir", default=None, help="Output dir (default: <storyboard>/renders/ai-clips/<provider>)")
@click.option("--frames", default=None, help="Only these frames, e.g. 1,3,5")
@click.option("--resolution", default="1080p", help="480p | 720p | 1080p (provider-dependent)")
@click.option("--ratio", default=None, help="Aspect ratio, e.g. 16:9 (default: from storyboard format)")
@click.option("--duration", type=int, default=None, help="Override per-clip seconds (default: frame duration)")
@click.option("--include-voiceover", is_flag=True, help="Feed the frame voiceover into the prompt")
@click.option("--generate-audio", is_flag=True, help="Ask the model for a native audio track")
@click.option("--watermark", is_flag=True, help="Keep the provider watermark")
@click.option("--style", default=None, help="Global style suffix appended to every prompt")
@click.option("--seed", type=int, default=None, help="Fixed seed for reproducibility")
@click.option("--poll-interval", type=int, default=10, help="Seconds between status polls")
@click.option("--max-wait", type=int, default=900, help="Give up on a task after N seconds")
@click.option("--dry-run", is_flag=True, help="Print the prompts, call nothing")
@click.option("--concat", is_flag=True, help="Stitch the finished clips into one mp4 (needs ffmpeg)")
def gen_video_cmd(
    storyboard,
    provider,
    out_dir,
    frames,
    resolution,
    ratio,
    duration,
    include_voiceover,
    generate_audio,
    watermark,
    style,
    seed,
    poll_interval,
    max_wait,
    dry_run,
    concat,
):
    """Generate one AI video clip per frame of STORYBOARD (a STORYBOARD.md)."""
    from clip_weave.adapters.video_gen import VideoGenError
    from clip_weave.core.video_pipeline import concat_clips, generate_clips

    frame_list = None
    if frames:
        try:
            frame_list = [int(x) for x in frames.replace(" ", "").split(",") if x]
        except ValueError:
            click.echo(f"--frames must be a comma-separated list of numbers, got {frames!r}", err=True)
            sys.exit(2)

    try:
        results = generate_clips(
            storyboard,
            provider=provider,
            out_dir=out_dir,
            frames=frame_list,
            resolution=resolution,
            ratio=ratio,
            duration=duration,
            include_voiceover=include_voiceover,
            generate_audio=generate_audio,
            watermark=watermark,
            style=style,
            seed=seed,
            poll_interval=poll_interval,
            max_wait=max_wait,
            dry_run=dry_run,
            report=lambda msg: click.echo(msg),
        )
    except VideoGenError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    ok = [r for r in results if r.state in ("succeeded", "dry-run")]
    click.echo(f"\n{len(ok)}/{len(results)} clips ready")

    if concat and not dry_run and any(r.video_path for r in results):
        first = next(r for r in results if r.video_path)
        dest = Path(first.video_path).parent / "full.mp4"
        try:
            concat_clips(results, dest, report=lambda m: click.echo(m))
        except VideoGenError as exc:
            click.echo(str(exc), err=True)

    for r in results:
        if r.state == "failed":
            click.echo(f"  frame {r.index}: {r.error}", err=True)
    if len(ok) != len(results):
        sys.exit(1)


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
cli.add_command(gen_video_cmd, name="gen-video")

if __name__ == "__main__":
    cli()
