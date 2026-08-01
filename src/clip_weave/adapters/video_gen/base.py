"""Shared plumbing for gateway-hosted video-generation models.

All three providers (Volcengine Ark / 豆包, Alibaba DashScope / 通义万相,
Google Vertex AI / Veo) use the same async shape:

    submit → task id → poll until terminal → fetch a video URL (or bytes)

`VideoModel` captures that shape; each provider subclass only implements the
three protocol-specific bits: `submit`, `poll`, and how the result is fetched.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import requests

logger = logging.getLogger(__name__)

TaskState = Literal["pending", "running", "succeeded", "failed"]

DEFAULT_TIMEOUT = 60


class VideoGenError(RuntimeError):
    """Raised for configuration and non-recoverable API errors."""


@dataclass
class ProviderConfig:
    """Per-provider gateway config, read from environment variables."""

    name: str
    base_url: str
    api_key: str
    model: str
    extra: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(
        cls,
        name: str,
        prefix: str,
        *,
        default_base_url: str = "",
        default_model: str = "",
        extra_keys: tuple[str, ...] = (),
    ) -> "ProviderConfig":
        base = os.getenv(f"{prefix}_BASE_URL", default_base_url).strip().rstrip("/")
        # The company gateway issues one key for every route, so fall back to the
        # shared key rather than forcing three copies of it into .env.
        key = (
            os.getenv(f"{prefix}_API_KEY")
            or os.getenv("AI_GATEWAY_API_KEY")
            or os.getenv("GEMINI_API_KEY")
            or ""
        ).strip()
        model = os.getenv(f"{prefix}_MODEL", default_model).strip()
        extra = {k: os.getenv(f"{prefix}_{k}", "").strip() for k in extra_keys}
        return cls(name=name, base_url=base, api_key=key, model=model, extra=extra)

    def require(self) -> None:
        missing = [n for n, v in (("base_url", self.base_url), ("api_key", self.api_key), ("model", self.model)) if not v]
        if missing:
            raise VideoGenError(
                f"{self.name}: missing {', '.join(missing)} — set the matching "
                f"*_BASE_URL / *_API_KEY / *_MODEL environment variables in .env"
            )


@dataclass
class TaskStatus:
    state: TaskState
    raw: dict[str, Any]
    video_url: str | None = None
    video_b64: str | None = None
    error: str | None = None


@dataclass
class VideoRequest:
    prompt: str
    duration: int = 5
    ratio: str = "16:9"
    resolution: str = "1080p"
    negative_prompt: str | None = None
    seed: int | None = None
    generate_audio: bool = False
    watermark: bool = False
    image_url: str | None = None  # optional first-frame reference


class VideoModel:
    """Base class — subclasses implement `submit()` and `poll()`."""

    #: seconds the provider accepts, used to clamp storyboard durations
    duration_range: tuple[int, int] = (5, 10)
    #: durations the provider accepts, when it only accepts a fixed set
    duration_choices: tuple[int, ...] | None = None

    def __init__(self, cfg: ProviderConfig, session: requests.Session | None = None):
        cfg.require()
        self.cfg = cfg
        self.session = session or requests.Session()

    # ── provider protocol ────────────────────────────────────────────────────
    def submit(self, req: VideoRequest) -> str:  # pragma: no cover - abstract
        raise NotImplementedError

    def poll(self, task_id: str) -> TaskStatus:  # pragma: no cover - abstract
        raise NotImplementedError

    # ── shared helpers ───────────────────────────────────────────────────────
    @property
    def model(self) -> str:
        return self.cfg.model

    def clamp_duration(self, seconds: float | None) -> int:
        if not seconds:
            seconds = self.duration_range[0]
        if self.duration_choices:
            return min(self.duration_choices, key=lambda c: abs(c - seconds))
        lo, hi = self.duration_range
        return int(max(lo, min(hi, round(seconds))))

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.cfg.api_key}",
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        url: str,
        *,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> dict[str, Any]:
        merged = {**self._headers(), **(headers or {})}
        logger.debug("%s %s %s", method, url, json)
        try:
            resp = self.session.request(method, url, json=json, headers=merged, timeout=timeout)
        except requests.RequestException as exc:
            raise VideoGenError(f"{self.cfg.name}: request to {url} failed: {exc}") from exc

        if resp.status_code >= 400:
            raise VideoGenError(
                f"{self.cfg.name}: HTTP {resp.status_code} from {url} — {resp.text[:500]}"
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise VideoGenError(
                f"{self.cfg.name}: non-JSON response from {url} — {resp.text[:200]}"
            ) from exc

    def download(self, status: TaskStatus, dest: Path) -> Path:
        """Persist a finished task's video to `dest`."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        if status.video_url:
            url = status.video_url
            if url.startswith("gs://"):
                # Only works for publicly readable objects; otherwise use gsutil.
                url = "https://storage.googleapis.com/" + url[len("gs://") :]
            with self.session.get(url, stream=True, timeout=600) as resp:
                resp.raise_for_status()
                with dest.open("wb") as fh:
                    for chunk in resp.iter_content(chunk_size=1 << 16):
                        if chunk:
                            fh.write(chunk)
            return dest
        if status.video_b64:
            import base64

            dest.write_bytes(base64.b64decode(status.video_b64))
            return dest
        raise VideoGenError(f"{self.cfg.name}: task finished without a video payload")
