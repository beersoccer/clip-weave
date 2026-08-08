"""阿里 通义万相 (Wan) — DashScope async video-synthesis protocol.

Upstream reference (Alibaba Cloud Model Studio, text-to-video API):
POST `{base}/api/v1/services/aigc/video-generation/video-synthesis` with the
`X-DashScope-Async: enable` header returns `{"output": {"task_id": …,
"task_status": "PENDING"}}`; GET `{base}/api/v1/tasks/{task_id}` returns the
task with `output.task_status` in PENDING / RUNNING / SUCCEEDED / FAILED and
`output.video_url` on success (valid 24h).
Docs: https://help.aliyun.com/en/model-studio/text-to-video-api-reference
(content rephrased for compliance with licensing restrictions).

Two request dialects exist:
  * wan2.7 — `parameters.resolution` (720P/1080P) + `parameters.ratio`
  * wan2.6 and earlier — `parameters.size` ("1280*720")
`ALI_VIDEO_PROTOCOL=wan27|legacy` selects one; `auto` (default) infers it from
the model name.
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
    "pending": "pending",
    "running": "running",
    "succeeded": "succeeded",
    "failed": "failed",
    "canceled": "failed",
    "cancelled": "failed",
    "unknown": "failed",
}

# width*height by (resolution tier, aspect ratio) — legacy `size` dialect.
_SIZE_TABLE = {
    ("480p", "16:9"): "832*480",
    ("480p", "9:16"): "480*832",
    ("480p", "1:1"): "624*624",
    ("720p", "16:9"): "1280*720",
    ("720p", "9:16"): "720*1280",
    ("720p", "1:1"): "960*960",
    ("720p", "4:3"): "1088*832",
    ("720p", "3:4"): "832*1088",
    ("1080p", "16:9"): "1920*1080",
    ("1080p", "9:16"): "1080*1920",
    ("1080p", "1:1"): "1440*1440",
    ("1080p", "4:3"): "1632*1248",
    ("1080p", "3:4"): "1248*1632",
}
_LEGACY_RATIOS = frozenset(ratio for _, ratio in _SIZE_TABLE)
_LEGACY_RESOLUTIONS = frozenset(resolution for resolution, _ in _SIZE_TABLE)


def load_config() -> ProviderConfig:
    return ProviderConfig.from_env(
        "ali",
        "ALI_VIDEO",
        default_base_url="http://aigateway.t1.test.noahgrouptest.com/alivideo",
        # wan2.7-t2v (default as of 2026-08) — wan2.5-t2v-preview is a superseded
        # preview build. Confirmed available on this gateway via
        # `scripts/verify_video_gateway.py --models --provider ali`.
        default_model="wan2.7-t2v",
        extra_keys=("SUBMIT_PATH", "TASK_PATH", "PROTOCOL"),
    )


class AliVideoModel(VideoModel):
    """Text-to-video via DashScope's async video-synthesis endpoint."""

    duration_range = (2, 15)

    @property
    def capabilities(self) -> ProviderCapabilities:
        if self._wan27:
            ratios = frozenset()
            resolutions = frozenset()
        else:
            ratios = _LEGACY_RATIOS
            resolutions = _LEGACY_RESOLUTIONS
        return ProviderCapabilities(
            ratios=ratios,
            resolutions=resolutions,
            duration_range=self.duration_range,
            duration_choices=self.duration_choices,
        )

    @property
    def _submit_url(self) -> str:
        path = (
            self.cfg.extra.get("SUBMIT_PATH")
            or "/api/v1/services/aigc/video-generation/video-synthesis"
        )
        return f"{self.cfg.base_url}/{path.lstrip('/')}"

    def _task_url(self, task_id: str) -> str:
        path = self.cfg.extra.get("TASK_PATH") or "/api/v1/tasks/{task_id}"
        if "{task_id}" not in path:
            path = path.rstrip("/") + "/{task_id}"
        return f"{self.cfg.base_url}/{path.lstrip('/').format(task_id=task_id)}"

    @property
    def _wan27(self) -> bool:
        proto = (self.cfg.extra.get("PROTOCOL") or "auto").lower()
        if proto in ("wan27", "wan2.7", "new"):
            return True
        if proto in ("legacy", "wan26", "wan2.6", "old"):
            return False
        return "2.7" in self.model  # auto

    def submit(self, req: VideoRequest) -> str:
        inputs: dict[str, Any] = {"prompt": req.prompt}
        if req.negative_prompt:
            inputs["negative_prompt"] = req.negative_prompt

        params: dict[str, Any] = {
            "duration": self.clamp_duration(req.duration),
            "prompt_extend": True,
            "watermark": req.watermark,
        }
        tier = req.resolution.lower().replace("P", "p")
        if self._wan27:
            params["resolution"] = tier.upper()  # 720P / 1080P
            params["ratio"] = req.ratio
        else:
            try:
                params["size"] = _SIZE_TABLE[(tier, req.ratio)]
            except KeyError as exc:
                raise VideoGenError(
                    f"ali: unsupported legacy size combination {tier}/{req.ratio}"
                ) from exc
        if req.seed is not None:
            params["seed"] = req.seed

        payload = {"model": self.model, "input": inputs, "parameters": params}
        data = self._request(
            "POST",
            self._submit_url,
            json=payload,
            headers={"X-DashScope-Async": "enable"},
        )
        task_id = (data.get("output") or {}).get("task_id")
        if not task_id:
            raise VideoGenError(
                f"ali: no task_id in submit response — {data.get('code') or ''} "
                f"{data.get('message') or data}"
            )
        return str(task_id)

    def poll(self, task_id: str) -> TaskStatus:
        data = self._request("GET", self._task_url(task_id))
        out = data.get("output") or {}
        raw_state = str(out.get("task_status") or "").lower()
        state = _STATE_MAP.get(raw_state, "running")
        message = out.get("message") or data.get("message")
        return TaskStatus(
            state=state,  # type: ignore[arg-type]
            raw=data,
            video_url=out.get("video_url") or None,
            error=message if state == "failed" else None,
        )
