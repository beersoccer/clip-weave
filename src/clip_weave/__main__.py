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
@click.option(
    "--profile",
    type=click.Choice(["html_launch", "t2v_brand_film", "ask"]),
    default="ask",
    help="Production profile: html_launch | t2v_brand_film | ask (default)",
)
def run_cmd(url, message, project, videos_dir, length, workflow, profile):
    """Route a video request and prepare the HF project for delegation."""
    cfg = load_config()
    project_name = project or _derive_project_name(url, message)
    user_input = f"{message} {url or ''}".strip()
    if workflow:
        user_input = f"{workflow} {user_input}"

    production_profile = _choose_production_profile(
        Path(videos_dir) / project_name,
        profile,
    )
    project_dir = pipeline_run(
        user_input=user_input,
        project_name=project_name,
        videos_dir=Path(videos_dir),
        message=message,
        length=length,
        cfg=cfg,
        production_profile=production_profile,
    )
    click.echo(f"Project ready: {project_dir}")


def _choose_production_profile(project_dir: Path, choice: str) -> str:
    """Choose the profile before project setup and delegation writes the BRIEF."""
    from clip_weave.core import render_path as rp

    if choice != "ask":
        click.echo(f"Production Profile: {choice}")
        return choice

    existing, source = rp.resolve(project_dir)
    if existing:
        click.echo(f"Production Profile: {existing} (from {source})")
        return existing

    click.echo(
        "\nProduction Profile 未指定。\n"
        "  html_launch     HyperFrames 成片 — 精确文字/品牌色/数据图表\n"
        "  t2v_brand_film  生成式品牌片 — 写实镜头；当前为逐镜头视频生成路径\n"
        "  每个项目只能选择一个主生产链。"
    )
    if not sys.stdin.isatty():
        click.echo(f"非交互环境，按默认 {rp.DEFAULT} 处理（用 --profile 显式指定）")
        return rp.DEFAULT

    picked = click.prompt(
        "选择 Production Profile", type=click.Choice(list(rp.PROFILES)), default=rp.DEFAULT, show_default=True
    )
    click.echo(f"已选择 Production Profile：{picked}（将写入 BRIEF.md）")
    if picked == "t2v_brand_film":
        click.echo(
            f"下一步：uv run python -m clip_weave gen-video {project_dir}/STORYBOARD.md "
            "--provider doubao --dry-run"
        )
    return picked


@cli.command("guard")
@click.argument("project_dir")
def guard_cmd(project_dir):
    """Run Rule Guard pre-flight on compositions in PROJECT_DIR."""
    from clip_weave.core import render_path as rp
    from clip_weave.core.storyboard import parse_storyboard

    p = Path(project_dir)
    compositions_dir = p / "compositions"
    if not compositions_dir.exists():
        click.echo(f"No compositions/ directory found in {p}", err=True)
        sys.exit(1)
    storyboard = p / "STORYBOARD.md"
    if storyboard.is_file():
        try:
            rp.validate_frames([frame.meta for frame in parse_storyboard(storyboard).frames])
        except rp.ProfileError as exc:
            raise click.UsageError(str(exc)) from exc
    ok = pipeline_guard(compositions_dir, project_dir=p)
    if ok:
        click.echo("Rule Guard: all clear")
    else:
        click.echo("Rule Guard: violations need attention — see log above", err=True)
        sys.exit(1)


@cli.command("match-assets")
@click.argument("project_dir")
@click.option("--query", default=None, help="Override query text (default: BRIEF.md message)")
@click.option(
    "--from-storyboard",
    is_flag=True,
    help="Match every frame's scene: line and print the ranking (does not modify STORYBOARD.md)",
)
def match_assets_cmd(project_dir, query, from_storyboard):
    """Run Asset Matcher on PROJECT_DIR capture/ assets."""
    from clip_weave.adapters.asset_matcher import match_assets
    p = Path(project_dir)

    if from_storyboard:
        from clip_weave.core.storyboard import parse_storyboard

        sb_path = p / "STORYBOARD.md"
        if not sb_path.exists():
            click.echo(f"No STORYBOARD.md in {p}", err=True)
            sys.exit(1)
        sb = parse_storyboard(sb_path)
        frames = [f for f in sb.frames if f.scene]
        if not frames:
            click.echo("No frames with a `scene:` field found", err=True)
            sys.exit(1)
        rankings = match_assets(p, [f.scene for f in frames])
        for frame, ranked in zip(frames, rankings):
            click.echo(f"\nFrame {frame.index} — {frame.title}")
            click.echo(f"  query: {frame.scene[:90]}")
            if not ranked:
                click.echo("  (no candidates — check capture/extracted/asset-descriptions.md)")
                continue
            for rank, asset in enumerate(ranked[:3], 1):
                click.echo(f"  {rank}. {asset['filename']}")
                click.echo(f"     {asset.get('description', '')[:100]}")
        return

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


@cli.command("route")
@click.argument("message")
@click.option("--url", default=None, help="Include a source URL in the routing input")
@click.option("--no-semantic", is_flag=True, help="Keyword routing only (offline behaviour)")
@click.option("--compare", is_flag=True, help="Show semantic and keyword picks side by side")
def route_cmd(message, url, no_semantic, compare):
    """Show which HF workflow MESSAGE routes to, and why."""
    from clip_weave.core.intent_router import (
        detect_source_type,
        detect_workflow_by_keywords,
        detect_workflow_explained,
    )

    user_input = f"{message} {url or ''}".strip()
    source_type, source_url = detect_source_type(user_input)

    if compare or no_semantic:
        kw = detect_workflow_by_keywords(user_input, source_type)
        click.echo(f"keyword : {kw}")
        if no_semantic:
            return

    workflow, decision = detect_workflow_explained(user_input, source_type)
    click.echo(f"semantic: {workflow}")
    click.echo(f"  method={decision.method} confidence={decision.confidence:.2f}")
    if decision.reason:
        click.echo(f"  reason={decision.reason}")
    click.echo(f"  source_type={source_type}" + (f" url={source_url}" if source_url else ""))


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
@click.option(
    "--regenerate-prompts",
    is_flag=True,
    help="Rebuild T2V-PROMPTS.md from STORYBOARD.md, discarding manual edits",
)
@click.option(
    "--prompts-only",
    is_flag=True,
    help="Write/refresh T2V-PROMPTS.md and stop (no generation, no cost)",
)
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
    regenerate_prompts,
    prompts_only,
):
    """Generate one AI video clip per frame of STORYBOARD (a STORYBOARD.md).

    Prompts live in a sibling `T2V-PROMPTS.md`: it is built from the storyboard on
    first run, then reused (and hand-editable) on every later run.
    """
    from clip_weave.adapters.video_gen import VideoGenError
    from clip_weave.core import render_path as rp
    from clip_weave.core.t2v_prompt import literal_prompt, load_or_create
    from clip_weave.core.video_pipeline import concat_clips, generate_clips

    storyboard_path = Path(storyboard)
    project_dir = storyboard_path.parent

    profile, source = rp.resolve(project_dir)
    if profile is None:
        raise click.UsageError(
            "gen-video requires BRIEF.md to select production_profile: t2v_brand_film; "
            "create the project with `run --profile t2v_brand_film` first."
        )
    if rp.engine(profile) != "t2v":
        raise click.UsageError(
            f"gen-video is unavailable for production_profile: {profile} ({source}); "
            "use the HyperFrames workflow for html_launch projects."
        )

    doc, prompts_path, created = load_or_create(
        storyboard_path,
        regenerate=regenerate_prompts,
        provider=provider,
        resolution=resolution,
        include_voiceover=include_voiceover,
        include_audio=generate_audio,
    )
    click.echo(f"{'wrote' if created else 'using'} {prompts_path}")
    if not created and not regenerate_prompts:
        ignored_flags = [
            name for name, value in (
                ("--style", style),
                ("--include-voiceover", include_voiceover),
                ("--generate-audio", generate_audio),
            )
            if value
        ]
        if ignored_flags:
            click.echo(
                f"  注意：{', '.join(ignored_flags)} 对已存在的 {prompts_path.name} 不生效——"
                "该文件已生成的提示词优先。用 --regenerate-prompts 从 STORYBOARD.md 重建"
                "（会丢弃手工编辑），或直接编辑该文件。"
            )
    rewritten = [s.index for s in doc.specs if "rewritten" in (s.notes or "")]
    if rewritten:
        click.echo(
            f"  scene rewritten: frame {', '.join(map(str, rewritten))} 的图文意图已由 LLM "
            "改写为可拍摄镜头 — 生成前建议过一遍"
        )
    flagged = [s.index for s in doc.specs if s.needs_review]
    if flagged:
        click.echo(
            f"  needs_review: frame {', '.join(map(str, flagged))} 以图文/数据为主，未能自动"
            "改写（未配置网关）— 视频模型渲染文字不可靠；请修订提示词，或重新选择整个项目的 "
            "Production Profile"
        )
    if prompts_only:
        click.echo("--prompts-only：未调用任何模型。编辑该文件后再跑一次即可生效。")
        return

    prompt_overrides = {s.index: literal_prompt(s) for s in doc.specs}
    duration_overrides = {s.index: s.duration for s in doc.specs}
    negative_overrides = {s.index: s.negative for s in doc.specs}
    reference_overrides = {s.index: s.reference for s in doc.specs}
    reference_requirements = {s.index: s.reference_requirement for s in doc.specs}
    reference_sources = {s.index: getattr(s, "reference_source", None) or s.reference for s in doc.specs}
    reference_licenses = {
        s.index: getattr(s, "reference_license", None)
        for s in doc.specs
        if getattr(s, "reference_license", None)
    }

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
            prompt_overrides=prompt_overrides,
            duration_overrides=duration_overrides,
            negative_overrides=negative_overrides,
            reference_overrides=reference_overrides,
            reference_requirements=reference_requirements,
            reference_sources=reference_sources,
            reference_licenses=reference_licenses,
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
cli.add_command(route_cmd, name="route")

if __name__ == "__main__":
    cli()
