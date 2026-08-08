"""豆包 / Seedance — Volcengine Ark content-generation protocol.

Upstream reference (Ark): POST `{base}/api/v3/contents/generations/tasks`
returns `{"id": "cgt-..."}`; GET the same path plus `/{id}` returns
`{"status": "queued|running|succeeded|failed|cancelled", "content": {"video_url": …}}`.
Docs summary: https://apidog.com/blog/seedance-2-0-api/ (content rephrased for
compliance with licensing restrictions).

Through the company gateway the upstream suffix is preserved by default:

    DOUBAO_VIDEO_BASE_URL=http://aigateway.t1.test.noahgrouptest.com/doubaovideo
    → POST http://aigateway.t1.test.noahgrouptest.com/doubaovideo/api/v3/contents/generations/tasks

Override `DOUBAO_VIDEO_TASKS_PATH` if the gateway flattens the path.
"""

from __future__ import annotations

from typing import Any

from .base import (
    ProviderCapabilities,
    ProviderConfig,
    TaskStatus,
    VideoGenError,
    VideoModel,
    VideoRequest,
)

_STATE_MAP = {
    "queued": "pending",
    "pending": "pending",
    "created": "pending",
    "running": "running",
    "processing": "running",
    "succeeded": "succeeded",
    "success": "succeeded",
    "completed": "succeeded",
    "failed": "failed",
    "cancelled": "failed",
    "canceled": "failed",
    "expired": "failed",
}


def load_config() -> ProviderConfig:
    return ProviderConfig.from_env(
        "doubao",
        "DOUBAO_VIDEO",
        default_base_url="http://aigateway.t1.test.noahgrouptest.com/doubaovideo",
        # Seedance 2.0 (default as of 2026-08) — 1.0-pro is the prior generation and
        # 1.5-pro is not provisioned on this gateway (404 InvalidEndpointOrModel).
        # Confirmed on the gateway: `scripts/verify_video_gateway.py --models --provider doubao`.
        default_model="doubao-seedance-2-0-260128",
        extra_keys=("TASKS_PATH", "DURATIONS"),
    )


class DoubaoVideoModel(VideoModel):
    """Text/image-to-video via Ark's `contents/generations/tasks` endpoint."""

    # Seedance 2.0 accepts 4–15s (confirmed against the gateway); 1.0-pro only
    # accepts 5 or 10. Set DOUBAO_VIDEO_DURATIONS (e.g. "4-15" or "5,10") if you
    # switch DOUBAO_VIDEO_MODEL to a model with different limits.
    duration_range = (4, 15)
    duration_choices = None

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            ratios=frozenset(),
            resolutions=frozenset(),
            duration_range=self.duration_range,
            duration_choices=self.duration_choices,
            reference_uri_schemes=frozenset({"http", "https"}),
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        spec = (self.cfg.extra.get("DURATIONS") or "").strip()
        if not spec:
            return
        if "-" in spec:
            lo, _, hi = spec.partition("-")
            self.duration_range = (int(lo), int(hi))
            self.duration_choices = None
        else:
            self.duration_choices = tuple(int(x) for x in spec.split(",") if x.strip())

    @property
    def _tasks_url(self) -> str:
        path = self.cfg.extra.get("TASKS_PATH") or "/api/v3/contents/generations/tasks"
        return f"{self.cfg.base_url}/{path.lstrip('/')}"

    def submit(self, req: VideoRequest) -> str:
        content: list[dict[str, Any]] = [{"type": "text", "text": req.prompt}]
        if req.image_url:
            content.append({"type": "image_url", "image_url": {"url": req.image_url}})

        payload: dict[str, Any] = {
            "model": self.model,
            "content": content,
            "resolution": req.resolution.lower(),
            "ratio": req.ratio,
            "duration": self.clamp_duration(req.duration),
            "watermark": req.watermark,
        }
        if req.seed is not None:
            payload["seed"] = req.seed
        if req.generate_audio:
            payload["generate_audio"] = True

        data = self._request("POST", self._tasks_url, json=payload)
        task_id = data.get("id") or data.get("task_id") or (data.get("data") or {}).get("id")
        if not task_id:
            raise VideoGenError(f"doubao: no task id in submit response — {data}")
        return str(task_id)

    def poll(self, task_id: str) -> TaskStatus:
        data = self._request("GET", f"{self._tasks_url}/{task_id}")
        raw_state = str(data.get("status") or data.get("task_status") or "").lower()
        state = _STATE_MAP.get(raw_state, "running")
        content = data.get("content") or {}
        error = data.get("error")
        return TaskStatus(
            state=state,  # type: ignore[arg-type]
            raw=data,
            video_url=content.get("video_url") or content.get("url"),
            error=(error if isinstance(error, str) else (error or {}).get("message")) if error else None,
        )
