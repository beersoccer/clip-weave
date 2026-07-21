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

_MAX_FRAMES = 20

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


def _extract_frames(
    video_path: str,
    scene_threshold: float,
    frames_dir: Path,
) -> None:
    """Extract frames via FFmpeg scene detection; fallback to fps=1 if none extracted."""
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True, exist_ok=True)
    output_pattern = str(frames_dir / "frame_%04d.jpg")

    result = subprocess.run(
        [
            "ffmpeg", "-y", "-i", video_path,
            "-vf", f"select='gt(scene,{scene_threshold})',scale=1280:720",
            "-vsync", "vfr",
            output_pattern,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise VideoAnalysisError(
            f"FFmpeg exited with code {result.returncode}",
            stderr=result.stderr,
        )

    # Fallback if scene detection produced no frames
    extracted = sorted(frames_dir.glob("frame_*.jpg"))
    if not extracted:
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-i", video_path,
                "-vf", "fps=1",
                output_pattern,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise VideoAnalysisError(
                f"FFmpeg fallback exited with code {result.returncode}",
                stderr=result.stderr,
            )


def _load_frames_as_messages(frames_dir: Path) -> list[dict]:
    """Load up to _MAX_FRAMES JPEGs as OpenAI vision content parts."""
    frame_files = sorted(frames_dir.glob("frame_*.jpg"))[:_MAX_FRAMES]
    parts = []
    for frame_path in frame_files:
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
    1. Extract frames via FFmpeg scene detection (fallback: fps=1).
    2. Encode frames and send to the configured LLM for structured analysis.
    3. Parse and validate the response against ShotsOutput schema.
    """
    _extract_frames(video_path, scene_threshold, frames_dir)

    frame_parts = _load_frames_as_messages(frames_dir)
    if not frame_parts:
        raise VideoAnalysisError(
            "No frames could be extracted from the video",
            stderr="Both scene-detection and fps=1 extraction produced zero frames",
        )

    api_key = cfg.video_analysis_api_key if cfg else ""
    base_url = cfg.video_analysis_base_url if cfg else None
    model = cfg.video_analysis_model if cfg else "gemini-2.5-flash"

    if not api_key:
        logger.warning(
            "VIDEO_ANALYSIS_API_KEY is empty — LLM call will fail. "
            "Set VIDEO_ANALYSIS_API_KEY in .env"
        )

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
