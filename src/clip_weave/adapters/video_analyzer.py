"""Video frame analyzer — FFmpeg scene detection + LLM multimodal analysis → ShotsOutput."""

import base64
import json
import logging
import re
import shutil
import subprocess
from pathlib import Path

from openai import OpenAI

from clip_weave.config import Config
from clip_weave.schemas.shots import ShotsOutput

logger = logging.getLogger(__name__)

# Frame extraction tuning
_MIN_FRAMES = 3           # always extract at least this many frames
_MAX_FRAMES = 40          # Gemini 2.5 Flash 1M context; 40 × ~800 tokens/frame ≈ 32K tokens
_TARGET_INTERVAL_SEC = 2.5  # 1 representative frame per N seconds (adaptive)

_ANALYSIS_PROMPT = """Analyze the provided video frames and return a JSON object that EXACTLY matches this schema:

{
  "style": {
    "pacing": "<fast|medium|slow>",
    "color_tone": "<warm|cool|neutral>",
    "typography": "<string describing font style>",
    "transition": "<cut|fade|swipe|zoom>",
    "aspect_ratio": "<e.g. 9:16, 16:9, 1:1>"
  },
  "shots": [
    {
      "index": <integer starting at 1>,
      "start": <float seconds>,
      "end": <float seconds>,
      "duration": <float seconds>,
      "type": "<hook|product|testimonial|cta>",
      "composition": "<string e.g. centered, rule-of-thirds>",
      "text_overlay": <string or null>,
      "visual_element": "<string describing what is seen>",
      "audio_cue": <string or null>
    }
  ],
  "narrative_structure": "<AIDA|PAS|Hook-Story-Offer|Before-After-Bridge>",
  "total_duration": <float seconds>,
  "shot_count": <integer matching length of shots array>
}

Return ONLY the JSON object. No explanation, no markdown wrapping."""


class VideoAnalysisError(Exception):
    """Raised when video analysis fails at any stage."""

    def __init__(self, message: str, stderr: str = "", raw_response: str = ""):
        super().__init__(message)
        self.stderr = stderr
        self.raw_response = raw_response


def _get_video_duration(video_path: str) -> float:
    """Return video duration in seconds via ffprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise VideoAnalysisError(
            "ffprobe failed to read video duration",
            stderr=result.stderr,
        )
    try:
        return float(result.stdout.strip())
    except ValueError as exc:
        raise VideoAnalysisError(
            f"ffprobe returned unexpected duration: {result.stdout!r}",
        ) from exc


def _extract_frames(
    video_path: str,
    scene_threshold: float,
    frames_dir: Path,
) -> None:
    """
    Extract representative frames using an adaptive multi-criteria strategy.

    Algorithm:
    1. ffprobe duration → compute adaptive max_gap = duration / target_count
    2. Single FFmpeg pass with combined select expression:
       - eq(n,0):                   always include the first frame
       - gt(scene, threshold):      capture every visual transition
       - gte(t-prev_selected_t, G): guarantee no silent segment > G seconds
    3. Append the last frame separately (FFmpeg scene filter often misses endings)
    4. If total > MAX_FRAMES (dense fast-cut video), subsample evenly while
       preserving first and last frames

    Image scale: 512px wide, auto height — adequate for LLM visual analysis
    and keeps per-frame token cost ~500 tokens on 16:9, ~1200 on 9:16.
    """
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True, exist_ok=True)

    duration = _get_video_duration(video_path)
    target = max(_MIN_FRAMES, min(_MAX_FRAMES, round(duration / _TARGET_INTERVAL_SEC)))
    max_gap = duration / target  # max seconds between any two selected frames

    output_pattern = str(frames_dir / "frame_%04d.jpg")

    # Combined select: first frame OR scene change OR time gap exceeded.
    # prev_selected_t is updated by FFmpeg after each selected frame.
    select_expr = (
        f"eq(n,0)"
        f"+gt(scene,{scene_threshold})"
        f"+gte(t-prev_selected_t,{max_gap:.3f})"
    )
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-i", video_path,
            "-vf", f"select='{select_expr}',scale=512:-2:flags=lanczos",
            "-vsync", "vfr",
            output_pattern,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise VideoAnalysisError(
            f"FFmpeg frame extraction failed (exit {result.returncode})",
            stderr=result.stderr,
        )

    # Always append the last frame — scene filter reliably misses video endings,
    # which often contain the CTA or brand sign-off.
    _append_last_frame(video_path, frames_dir)

    extracted = sorted(frames_dir.glob("frame_*.jpg"))
    n_raw = len(extracted)

    if n_raw == 0:
        raise VideoAnalysisError(
            "No frames extracted from video",
            stderr=result.stderr,
        )

    # Dense fast-cut videos may produce more frames than MAX_FRAMES.
    # Subsample evenly while always keeping first and last.
    if n_raw > _MAX_FRAMES:
        _subsample_to(extracted, _MAX_FRAMES)

    n_kept = min(n_raw, _MAX_FRAMES)
    logger.info(
        "Frame extraction: %.1fs video → %d raw → %d kept "
        "(target=%d, max_gap=%.1fs, threshold=%.2f)",
        duration, n_raw, n_kept, target, max_gap, scene_threshold,
    )


def _append_last_frame(video_path: str, frames_dir: Path) -> None:
    """Extract the last frame of the video and append it to frames_dir."""
    existing = sorted(frames_dir.glob("frame_*.jpg"))
    next_idx = len(existing) + 1
    out_path = frames_dir / f"frame_{next_idx:04d}.jpg"
    subprocess.run(
        [
            "ffmpeg", "-y", "-sseof", "-0.1", "-i", video_path,
            "-vf", "scale=512:-2:flags=lanczos",
            "-frames:v", "1",
            str(out_path),
        ],
        capture_output=True,
        text=True,
    )


def _subsample_to(frames: list[Path], keep: int) -> None:
    """
    Delete frames to keep exactly `keep` frames evenly distributed.
    First and last frames are always preserved.
    """
    n = len(frames)
    if keep >= n:
        return
    if keep == 1:
        keep_indices: set[int] = {0}
    else:
        keep_indices = {round(i * (n - 1) / (keep - 1)) for i in range(keep)}
    for i, path in enumerate(frames):
        if i not in keep_indices:
            path.unlink()


def _load_frames_as_messages(frames_dir: Path) -> list[dict]:
    """Load all extracted JPEGs as OpenAI vision content parts."""
    parts = []
    for frame_path in sorted(frames_dir.glob("frame_*.jpg")):
        b64 = base64.b64encode(frame_path.read_bytes()).decode("utf-8")
        parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
        })
    return parts


def _parse_response(text: str) -> dict:
    """Extract JSON from LLM response, handling markdown code blocks."""
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        text = match.group(1)
    return json.loads(text.strip())


def analyze_video(
    video_path: str,
    scene_threshold: float = 0.35,
    cfg: Config | None = None,
    frames_dir: Path = Path("output/frames"),
) -> ShotsOutput:
    """
    Analyze a video file and return structured shot data.

    Steps:
    1. Extract frames adaptively via FFmpeg (scene changes + temporal coverage).
    2. Encode frames and send to the configured LLM for structured analysis.
    3. Parse and validate the response against ShotsOutput schema.
    """
    _extract_frames(video_path, scene_threshold, frames_dir)

    frame_parts = _load_frames_as_messages(frames_dir)
    if not frame_parts:
        raise VideoAnalysisError(
            "No frames available for analysis",
            stderr="Frame extraction produced no files",
        )

    api_key = cfg.video_analysis_api_key if cfg else ""
    base_url = cfg.video_analysis_base_url if cfg else None
    model = cfg.video_analysis_model if cfg else "gemini-2.5-flash"

    if not api_key:
        logger.warning(
            "VIDEO_ANALYSIS_API_KEY is empty — LLM call will fail. "
            "Set VIDEO_ANALYSIS_API_KEY in .env"
        )

    # When no gateway is configured, use Gemini's OpenAI-compatible endpoint directly.
    if not base_url:
        base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
    client = OpenAI(base_url=base_url, api_key=api_key or "missing")

    messages = [
        {
            "role": "user",
            "content": [
                *frame_parts,
                {"type": "text", "text": _ANALYSIS_PROMPT},
            ],
        }
    ]

    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=4096,
        )
        raw_text = response.choices[0].message.content or ""
    except Exception as exc:
        hint = ""
        exc_lower = str(exc).lower()
        if "auth" in exc_lower or "api key" in exc_lower or "401" in exc_lower:
            hint = " — check VIDEO_ANALYSIS_API_KEY and VIDEO_ANALYSIS_BASE_URL in .env"
        elif "model" in exc_lower or "404" in exc_lower:
            hint = f" — check VIDEO_ANALYSIS_MODEL='{model}' is supported by your endpoint"
        logger.error("LLM API call failed: %s%s", exc, hint)
        raise VideoAnalysisError(
            f"LLM API call failed: {exc}{hint}",
            raw_response="",
        ) from exc

    try:
        data = _parse_response(raw_text)
    except json.JSONDecodeError as exc:
        raise VideoAnalysisError(
            "LLM returned invalid JSON",
            raw_response=raw_text,
        ) from exc

    try:
        return ShotsOutput.model_validate(data)
    except Exception as exc:
        raise VideoAnalysisError(
            f"Response failed schema validation: {exc}",
            raw_response=raw_text,
        ) from exc
