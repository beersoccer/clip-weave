"""HyperFrames adapter — HTML-to-video rendering with frame preservation."""

import subprocess
from pathlib import Path


class HyperFramesError(Exception):
    pass


def _output_path(output_dir: Path, video_name: str) -> Path:
    return output_dir / video_name


def _frames_dir(output_dir: Path) -> Path:
    return output_dir / "frames"


def _build_render_command(html_path: Path, output_path: Path) -> list[str]:
    # `npx hyperframes render` is run from the composition directory;
    # html_path is implicitly index.html / composition.html in cwd.
    return ["npx", "hyperframes", "render", "--output", str(output_path)]


def render_html_to_video(
    html_content: str,
    output_dir: Path,
    video_name: str = "final.mp4",
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    comp_dir = output_dir / "compositions"
    comp_dir.mkdir(exist_ok=True)
    html_path = comp_dir / "composition.html"
    html_path.write_text(html_content, encoding="utf-8")

    out_path = _output_path(output_dir, video_name)
    cmd = _build_render_command(html_path, out_path)
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(comp_dir))

    if result.returncode != 0:
        raise HyperFramesError(
            f"HyperFrames failed (code {result.returncode}): {result.stderr}\n"
            f"Frames preserved at {_frames_dir(output_dir)}"
        )
    return out_path
