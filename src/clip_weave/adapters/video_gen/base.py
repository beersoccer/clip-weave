"""Shared plumbing for gateway-hosted video-generation models.

All three providers (Volcengine Ark / 豆包, Alibaba DashScope / 通义万相,
Google Vertex AI / Veo) use the same async shape:

    submit → task id → poll until terminal → fetch a video URL (or bytes)

`VideoModel` captures that shape; each provider subclass only implements the
three protocol-specific bits: `submit`, `poll`, and how the result is fetched.
"""

from __future__ import annotations

import logging
import math
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

import requests

logger = logging.getLogger(__name__)

TaskState = Literal["pending", "running", "succeeded", "failed"]

DEFAULT_TIMEOUT = 60
DEFAULT_POLL_INTERVAL = 10
DEFAULT_MAX_WAIT = 900


class VideoGenError(RuntimeError):
    """Raised for configuration and non-recoverable API errors."""

    def __init__(
        self,
        message: str,
        *,
        error_class: Literal["network", "rate_limited", "server"] | None = None,
        status_code: int | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.error_class = error_class
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds


def _retry_after_seconds(headers: Any) -> float | None:
    value = headers.get("Retry-After") if headers else None
    if not isinstance(value, str):
        return None
    try:
        seconds = float(value)
        return seconds if math.isfinite(seconds) and seconds >= 0 else None
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    seconds = (retry_at - datetime.now(timezone.utc)).total_seconds()
    return seconds if seconds > 0 else None


def _safe_endpoint(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


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
        # Every provider has its own *_API_KEY slot. The company gateway issues one
        # key for every video route (including Vertex — it is proxied through the
        # same gateway, just with a different upstream path), so AI_GATEWAY_API_KEY
        # is a convenience fallback when a provider's own key is not set: configure
        # just that one variable and every provider works. A provider's own key,
        # when set, always wins.
        key = (os.getenv(f"{prefix}_API_KEY") or os.getenv("AI_GATEWAY_API_KEY") or "").strip()
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


@dataclass(frozen=True)
class ProviderCapabilities:
    """Static generation constraints declared by a provider adapter."""

    ratios: frozenset[str]
    resolutions: frozenset[str]
    duration_range: tuple[int, int]
    duration_choices: tuple[int, ...] | None = None
    reference_uri_schemes: frozenset[str] = frozenset()
    supported_resolution_ratios: frozenset[tuple[str, str]] | None = None


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

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            ratios=frozenset(),
            resolutions=frozenset(),
            duration_range=self.duration_range,
            duration_choices=self.duration_choices,
        )

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

    def _http_error(self, status_code: int, url: str, text: str, headers: Any) -> VideoGenError:
        error_class: Literal["rate_limited", "server"] | None = None
        retry_after = None
        if status_code == 429:
            error_class = "rate_limited"
            retry_after = _retry_after_seconds(headers)
        elif 500 <= status_code <= 599:
            error_class = "server"
        return VideoGenError(
            f"{self.cfg.name}: HTTP {status_code} from {_safe_endpoint(url)} — {text[:500]}",
            error_class=error_class,
            status_code=status_code,
            retry_after_seconds=retry_after,
        )

    def _request_error(self, url: str, exc: requests.RequestException) -> VideoGenError:
        error_class: Literal["network"] | None = None
        if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
            error_class = "network"
        return VideoGenError(
            f"{self.cfg.name}: request to {_safe_endpoint(url)} failed: {exc}", error_class=error_class
        )

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
            raise self._request_error(url, exc) from None

        if resp.status_code >= 400:
            raise self._http_error(resp.status_code, url, resp.text, resp.headers)
        try:
            return resp.json()
        except ValueError as exc:
            raise VideoGenError(
                f"{self.cfg.name}: non-JSON response from {_safe_endpoint(url)} — {resp.text[:200]}"
            ) from exc

    def wait(
        self,
        task_id: str,
        *,
        interval: int = DEFAULT_POLL_INTERVAL,
        max_wait: int = DEFAULT_MAX_WAIT,
        on_state: Any = None,
    ) -> TaskStatus:
        """Poll until the task reaches a terminal state or `max_wait` elapses."""
        deadline = time.time() + max_wait
        status = TaskStatus(state="pending", raw={})
        while time.time() < deadline:
            status = self.poll(task_id)
            if on_state:
                on_state(status)
            if status.state in ("succeeded", "failed"):
                return status
            time.sleep(interval)
        return TaskStatus(
            state="failed",
            raw=status.raw,
            error=f"timed out after {max_wait}s (last state: {status.state})",
        )

    def download(self, status: TaskStatus, dest: Path) -> Path:
        """Persist a finished task's video to `dest`."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        if status.video_url:
            url = status.video_url
            if url.startswith("gs://"):
                # Only works for publicly readable objects; otherwise use gsutil.
                url = "https://storage.googleapis.com/" + url[len("gs://") :]
            try:
                with self.session.get(url, stream=True, timeout=600) as resp:
                    if resp.status_code >= 400:
                        raise self._http_error(resp.status_code, url, resp.text, resp.headers)
                    with dest.open("wb") as fh:
                        for chunk in resp.iter_content(chunk_size=1 << 16):
                            if chunk:
                                fh.write(chunk)
            except VideoGenError:
                raise
            except requests.RequestException as exc:
                raise self._request_error(url, exc) from None
            return dest
        if status.video_b64:
            import base64

            dest.write_bytes(base64.b64decode(status.video_b64))
            return dest
        raise VideoGenError(f"{self.cfg.name}: task finished without a video payload")
