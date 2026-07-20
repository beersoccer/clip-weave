import json
from pathlib import Path
import click
from clip_weave.config import load_config
from clip_weave.pipeline import analyze, render
from clip_weave.schemas.shots import ShotsOutput
from clip_weave.schemas.brand_assets import BrandAssets


def _load_brand(brand_dir: str) -> BrandAssets:
    p = Path(brand_dir) / "brand_assets.json"
    if p.exists():
        return BrandAssets.model_validate(json.loads(p.read_text()))
    return BrandAssets(brand_name=Path(brand_dir).name)


@click.group()
def cli():
    pass


@cli.command()
@click.option("--video", required=True, help="Path to sample video")
@click.option("--output", default="output/shots.json", help="Output shots.json path")
def analyze_cmd(video: str, output: str):
    cfg = load_config()
    out_path = Path(output)
    shots = analyze(video, cfg, output_dir=out_path.parent)
    click.echo(f"Analysis complete: {out_path} ({shots.shot_count} shots)")


@cli.command()
@click.option("--video", required=True)
@click.option("--brand", required=True, help="Brand assets directory")
@click.option("--mode", default="hyperframes", type=click.Choice(["hyperframes"]))
@click.option("--html-model", default=None, help="claude or gpt4o (overrides env)")
def run_cmd(video: str, brand: str, mode: str, html_model: str):
    cfg = load_config()
    if html_model:
        cfg.html_gen_model = html_model
    brand_assets = _load_brand(brand)
    shots = analyze(video, cfg)
    output = render(shots, brand_assets, cfg)
    click.echo(f"Done: {output}")


@cli.command()
@click.option("--shots", required=True, help="Path to shots.json")
@click.option("--brand", required=True)
@click.option("--mode", default="hyperframes", type=click.Choice(["hyperframes"]))
@click.option("--html-model", default=None)
def render_cmd(shots: str, brand: str, mode: str, html_model: str):
    cfg = load_config()
    if html_model:
        cfg.html_gen_model = html_model
    shots_data = ShotsOutput.model_validate(json.loads(Path(shots).read_text()))
    brand_assets = _load_brand(brand)
    output = render(shots_data, brand_assets, cfg)
    click.echo(f"Done: {output}")


cli.add_command(analyze_cmd, name="analyze")
cli.add_command(run_cmd, name="run")
cli.add_command(render_cmd, name="render")

if __name__ == "__main__":
    cli()
