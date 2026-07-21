import json
import logging
import sys
from pathlib import Path

import click

from clip_weave.adapters.video_analyzer import VideoAnalysisError
from clip_weave.config import load_config
from clip_weave.pipeline import analyze, render
from clip_weave.schemas.brand_assets import BrandAssets
from clip_weave.schemas.shots import ShotsOutput


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.WARNING,
        format="[%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _load_brand(brand_dir: str) -> BrandAssets:
    p = Path(brand_dir) / "brand_assets.json"
    if p.exists():
        return BrandAssets.model_validate(json.loads(p.read_text()))
    return BrandAssets(brand_name=Path(brand_dir).name)


@click.group()
def cli():
    _setup_logging()


@cli.command()
@click.option("--video", required=True, help="Path to sample video")
@click.option("--output", default="output/shots.json", help="Output shots.json path")
def analyze_cmd(video: str, output: str):
    cfg = load_config()
    out_path = Path(output)
    try:
        shots = analyze(video, cfg, output_dir=out_path.parent)
    except VideoAnalysisError as exc:
        click.echo(f"Error: video analysis failed — {exc}", err=True)
        if exc.stderr:
            click.echo(f"  FFmpeg stderr: {exc.stderr}", err=True)
        sys.exit(1)
    click.echo(f"Analysis complete: {out_path} ({shots.shot_count} shots)")


@cli.command()
@click.option("--video", required=True)
@click.option("--brand", required=True, help="Brand assets directory")
@click.option("--mode", default="hyperframes", type=click.Choice(["hyperframes"]))
@click.option("--html-model", default=None, help="Model name for HTML generation (overrides HTML_GEN_MODEL)")
def run_cmd(video: str, brand: str, mode: str, html_model: str):
    cfg = load_config()
    if html_model:
        cfg.html_gen_model = html_model
    brand_assets = _load_brand(brand)
    try:
        shots = analyze(video, cfg)
    except VideoAnalysisError as exc:
        click.echo(f"Error: video analysis failed — {exc}", err=True)
        if exc.stderr:
            click.echo(f"  FFmpeg stderr: {exc.stderr}", err=True)
        sys.exit(1)
    try:
        output = render(shots, brand_assets, cfg)
    except ValueError as exc:
        click.echo(f"Error: rendering failed — {exc}", err=True)
        sys.exit(1)
    click.echo(f"Done: {output}")


@cli.command()
@click.option("--shots", required=True, help="Path to shots.json")
@click.option("--brand", required=True)
@click.option("--mode", default="hyperframes", type=click.Choice(["hyperframes"]))
@click.option("--html-model", default=None, help="Model name for HTML generation (overrides HTML_GEN_MODEL)")
def render_cmd(shots: str, brand: str, mode: str, html_model: str):
    cfg = load_config()
    if html_model:
        cfg.html_gen_model = html_model
    try:
        shots_data = ShotsOutput.model_validate(json.loads(Path(shots).read_text()))
    except Exception as exc:
        click.echo(f"Error: could not load shots.json — {exc}", err=True)
        sys.exit(1)
    brand_assets = _load_brand(brand)
    try:
        output = render(shots_data, brand_assets, cfg)
    except ValueError as exc:
        click.echo(f"Error: rendering failed — {exc}", err=True)
        sys.exit(1)
    click.echo(f"Done: {output}")


cli.add_command(analyze_cmd, name="analyze")
cli.add_command(run_cmd, name="run")
cli.add_command(render_cmd, name="render")

if __name__ == "__main__":
    cli()
