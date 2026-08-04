"""Google Veo — Vertex AI `predictLongRunning` protocol.

Upstream reference: POST
`{base}/v1/projects/{project}/locations/{location}/publishers/google/models/
{model}:predictLongRunning` with `{"instances": [{"prompt": …}], "parameters":
{"aspectRatio", "durationSeconds", "resolution", "sampleCount", "generateAudio",
"negativePrompt"}}` returns `{"name": "…/operations/…"}`; POST the same
resource path with `:fetchPredictOperation` and `{"operationName": …}` returns
the operation, and once `done` is true the videos arrive under
`response.videos[]` as `gcsUri` or `bytesBase64Encoded`.
Docs: https://cloud.google.com/vertex-ai/docs/reference/rest/v1/projects.locations.endpoints/predictLongRunning
(content rephrased for compliance with licensing restrictions.)

Confirmed against the real Vertex AI host — this is what the raw Google API
requires, project id included, no gateway-side shortcut exists for it:

    POST https://{location}-aiplatform.googleapis.com/v1/projects/{project}
        /locations/{location}/publishers/google/models/{model}:predictLongRunning

Through the company gateway the same resource path is proxied verbatim, still
authenticated with the gateway's own Bearer key (not a Google OAuth2 token —
the gateway host itself is `VERTEX_VIDEO_BASE_URL`, project/location just
become part of the *path*, they do not change how the request is authed):

    VERTEX_VIDEO_BASE_URL=http://aigateway.t1.test.noahgrouptest.sg/vertexvideo
    → POST {VERTEX_VIDEO_BASE_URL}/v1/projects/{project}/locations/{location}
        /publishers/google/models/{model}:predictLongRunning

`VERTEX_VIDEO_PROJECT` + `VERTEX_VIDEO_LOCATION` are therefore always required
(the resource path is meaningless without them); `VERTEX_VIDEO_MODEL_PATH`
still exists to pin the whole path wholesale for a non-standard gateway shape.
"""

from __future__ import annotations

from typing import Any

from .base import ProviderConfig, TaskStatus, VideoGenError, VideoModel, VideoRequest


def load_config() -> ProviderConfig:
    return ProviderConfig.from_env(
        "vertex",
        "VERTEX_VIDEO",
        default_base_url="http://aigateway.t1.test.noahgrouptest.sg/vertexvideo",
        default_model="veo-3.1-generate-001",
        extra_keys=("MODEL_PATH", "PROJECT", "LOCATION", "API_VERSION", "PUBLISHER"),
    )


class VertexVideoModel(VideoModel):
    """Text/image-to-video via Veo on Vertex AI."""

    # Veo 3.1 accepts 4 / 6 / 8 seconds, and only 16:9 or 9:16.
    duration_choices = (4, 6, 8)
    supported_ratios = ("16:9", "9:16")

    @property
    def _model_path(self) -> str:
        override = self.cfg.extra.get("MODEL_PATH")
        if override:
            return override.strip("/")
        publisher = self.cfg.extra.get("PUBLISHER") or "google"
        project = self.cfg.extra.get("PROJECT")
        location = self.cfg.extra.get("LOCATION") or "us-central1"
        if not project:
            raise VideoGenError(
                "vertex: VERTEX_VIDEO_PROJECT is required — Vertex's resource path is "
                "projects/{project}/locations/{location}/publishers/google/models/{model}, "
                "there is no path without a real GCP project id in it"
            )
        return (
            f"projects/{project}/locations/{location}"
            f"/publishers/{publisher}/models/{self.model}"
        )

    def _url(self, verb: str) -> str:
        version = self.cfg.extra.get("API_VERSION") or "v1"
        return f"{self.cfg.base_url}/{version}/{self._model_path}:{verb}"

    def submit(self, req: VideoRequest) -> str:
        instance: dict[str, Any] = {"prompt": req.prompt}
        if req.image_url:
            instance["image"] = {"gcsUri": req.image_url, "mimeType": "image/png"}

        ratio = req.ratio if req.ratio in self.supported_ratios else "16:9"
        params: dict[str, Any] = {
            "aspectRatio": ratio,
            "durationSeconds": self.clamp_duration(req.duration),
            "resolution": req.resolution.lower(),
            "sampleCount": 1,
            "generateAudio": req.generate_audio,
        }
        if req.negative_prompt:
            params["negativePrompt"] = req.negative_prompt
        if req.seed is not None:
            params["seed"] = req.seed

        data = self._request(
            "POST",
            self._url("predictLongRunning"),
            json={"instances": [instance], "parameters": params},
        )
        name = data.get("name")
        if not name:
            raise VideoGenError(f"vertex: no operation name in submit response — {data}")
        return str(name)

    def poll(self, operation_name: str) -> TaskStatus:
        data = self._request(
            "POST",
            self._url("fetchPredictOperation"),
            json={"operationName": operation_name},
        )
        if data.get("error"):
            err = data["error"]
            return TaskStatus(
                state="failed",
                raw=data,
                error=err.get("message") if isinstance(err, dict) else str(err),
            )
        if not data.get("done"):
            return TaskStatus(state="running", raw=data)

        response = data.get("response") or {}
        videos = response.get("videos") or response.get("generatedSamples") or []
        if not videos:
            filtered = response.get("raiMediaFilteredReasons") or []
            return TaskStatus(
                state="failed",
                raw=data,
                error="; ".join(map(str, filtered)) or "operation done but no videos returned",
            )
        video = videos[0]
        return TaskStatus(
            state="succeeded",
            raw=data,
            video_url=video.get("gcsUri") or video.get("uri") or (video.get("video") or {}).get("uri"),
            video_b64=video.get("bytesBase64Encoded"),
        )
