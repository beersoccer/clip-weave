"""Offline tests for the three gateway video-generation providers.

No real HTTP: a FakeSession records requests and returns canned JSON.
"""

import pytest
import requests

from clip_weave.adapters.video_gen import VideoGenError, VideoRequest, get_model
from clip_weave.adapters.video_gen.ali import AliVideoModel
from clip_weave.adapters.video_gen.base import ProviderConfig, TaskStatus
from clip_weave.adapters.video_gen.doubao import DoubaoVideoModel
from clip_weave.adapters.video_gen.vertex import VertexVideoModel

_NOT_JSON = object()


class FakeResponse:
    def __init__(self, payload, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text or str(payload)

    def json(self):
        if self._payload is _NOT_JSON:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    """Records every request and replays queued responses in order."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, json=None, headers=None, timeout=None):
        self.calls.append({"method": method, "url": url, "json": json, "headers": headers})
        return self.responses.pop(0) if self.responses else FakeResponse({})


def _cfg(name, base_url, model, **extra):
    return ProviderConfig(
        name=name, base_url=base_url, api_key="test-key", model=model, extra=dict(extra)
    )


# ── ProviderConfig ────────────────────────────────────────────────────────────

def test_require_lists_every_missing_field():
    cfg = ProviderConfig(name="ali", base_url="", api_key="", model="")
    with pytest.raises(VideoGenError) as exc:
        cfg.require()
    for field in ("base_url", "api_key", "model"):
        assert field in str(exc.value)


def test_from_env_falls_back_to_the_shared_gateway_key(monkeypatch):
    monkeypatch.delenv("DOUBAO_VIDEO_API_KEY", raising=False)
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "shared-key")
    monkeypatch.setenv("DOUBAO_VIDEO_BASE_URL", "http://gw/doubaovideo/")
    cfg = ProviderConfig.from_env("doubao", "DOUBAO_VIDEO", default_model="m")
    assert cfg.api_key == "shared-key"
    assert cfg.base_url == "http://gw/doubaovideo"  # trailing slash stripped


def test_from_env_prefers_providers_own_key_over_shared(monkeypatch):
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "shared-key")
    monkeypatch.setenv("DOUBAO_VIDEO_API_KEY", "doubao-own-key")
    cfg = ProviderConfig.from_env("doubao", "DOUBAO_VIDEO", default_model="m")
    assert cfg.api_key == "doubao-own-key"


def test_get_model_rejects_unknown_provider():
    with pytest.raises(VideoGenError, match="unknown provider"):
        get_model("midjourney")


# ── clamp_duration ────────────────────────────────────────────────────────────

def test_doubao_clamps_within_the_default_seedance_2_range():
    """Default model is Seedance 2.0, which accepts any 4-15s (no fixed choices) —
    confirmed against the gateway in scripts/verify_video_gateway.py --models."""
    vm = DoubaoVideoModel(_cfg("doubao", "http://gw/d", "doubao-seedance-2-0-260128"))
    assert vm.clamp_duration(5.851) == 6
    assert vm.clamp_duration(99) == 15
    assert vm.clamp_duration(None) == 4


def test_doubao_durations_fixed_choice_override_for_1_0_pro():
    """Seedance 1.0-pro only accepts 5 or 10 — set via DOUBAO_VIDEO_DURATIONS."""
    vm = DoubaoVideoModel(
        _cfg("doubao", "http://gw/d", "doubao-seedance-1-0-pro", DURATIONS="5,10")
    )
    assert vm.clamp_duration(5.851) == 5
    assert vm.clamp_duration(8) == 10
    assert vm.clamp_duration(None) == 5


def test_doubao_durations_range_override():
    vm = DoubaoVideoModel(_cfg("doubao", "http://gw/d", "seedance-2", DURATIONS="4-15"))
    assert vm.duration_range == (4, 15)
    assert vm.duration_choices is None
    assert vm.clamp_duration(12.4) == 12
    assert vm.clamp_duration(99) == 15


def test_doubao_durations_choice_list_override():
    vm = DoubaoVideoModel(_cfg("doubao", "http://gw/d", "seedance", DURATIONS="5,10,15"))
    assert vm.clamp_duration(13) == 15


def test_vertex_clamps_to_veo_choices():
    vm = VertexVideoModel(_cfg("vertex", "http://gw/v", "veo-3.1-generate-001"))
    assert vm.clamp_duration(5) == 4
    assert vm.clamp_duration(7) == 6  # ties resolve to the first nearest choice
    assert vm.clamp_duration(30) == 8


def test_ali_clamps_within_range():
    vm = AliVideoModel(_cfg("ali", "http://gw/a", "wan2.5-t2v-preview"))
    assert vm.clamp_duration(1) == 2
    assert vm.clamp_duration(99) == 15


# ── provider capabilities ───────────────────────────────────────────────────

def test_doubao_declares_http_reference_capabilities():
    vm = DoubaoVideoModel(_cfg("doubao", "http://gw/d", "seedance"))
    assert vm.capabilities.reference_uri_schemes == frozenset({"http", "https"})


def test_ali_legacy_capabilities_match_the_size_table_and_have_no_reference_support():
    vm = AliVideoModel(_cfg("ali", "http://gw/a", "wan2.5-t2v-preview"))
    assert vm.capabilities.ratios == frozenset({"16:9", "9:16", "1:1", "4:3", "3:4"})
    assert vm.capabilities.resolutions == frozenset({"480p", "720p", "1080p"})
    assert vm.capabilities.reference_uri_schemes == frozenset()


def test_vertex_declares_veo_capabilities():
    vm = VertexVideoModel(_cfg("vertex", "http://gw/v", "veo-3.1-generate-001"))
    assert vm.capabilities.ratios == frozenset({"16:9", "9:16"})
    assert vm.capabilities.duration_choices == (4, 6, 8)
    assert vm.capabilities.reference_uri_schemes == frozenset({"gs"})


# ── 豆包 / Seedance ───────────────────────────────────────────────────────────

def test_doubao_submit_builds_ark_payload():
    session = FakeSession(FakeResponse({"id": "cgt-123"}))
    vm = DoubaoVideoModel(_cfg("doubao", "http://gw/doubaovideo", "seedance"), session=session)

    task_id = vm.submit(
        VideoRequest(prompt="夜景轿车", duration=5, ratio="16:9", resolution="1080p", seed=7,
                     generate_audio=True)
    )

    assert task_id == "cgt-123"
    call = session.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "http://gw/doubaovideo/api/v3/contents/generations/tasks"
    assert call["headers"]["Authorization"] == "Bearer test-key"
    body = call["json"]
    assert body["content"] == [{"type": "text", "text": "夜景轿车"}]
    assert body["resolution"] == "1080p"
    assert body["ratio"] == "16:9"
    assert body["duration"] == 5
    assert body["seed"] == 7
    assert body["generate_audio"] is True


def test_doubao_submit_appends_reference_image():
    session = FakeSession(FakeResponse({"id": "cgt-1"}))
    vm = DoubaoVideoModel(_cfg("doubao", "http://gw/d", "seedance"), session=session)
    vm.submit(VideoRequest(prompt="p", image_url="https://cdn/first-frame.png"))
    content = session.calls[0]["json"]["content"]
    assert content[1] == {"type": "image_url",
                          "image_url": {"url": "https://cdn/first-frame.png"}}


def test_doubao_submit_honours_tasks_path_override():
    session = FakeSession(FakeResponse({"id": "x"}))
    vm = DoubaoVideoModel(
        _cfg("doubao", "http://gw/d", "seedance", TASKS_PATH="/flat/tasks"), session=session
    )
    vm.submit(VideoRequest(prompt="p"))
    assert session.calls[0]["url"] == "http://gw/d/flat/tasks"


def test_doubao_submit_without_task_id_raises():
    session = FakeSession(FakeResponse({"error": {"message": "quota"}}))
    vm = DoubaoVideoModel(_cfg("doubao", "http://gw/d", "seedance"), session=session)
    with pytest.raises(VideoGenError, match="no task id"):
        vm.submit(VideoRequest(prompt="p"))


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("queued", "pending"), ("running", "running"), ("succeeded", "succeeded"),
        ("completed", "succeeded"), ("failed", "failed"), ("cancelled", "failed"),
        ("expired", "failed"), ("something-new", "running"),
    ],
)
def test_doubao_state_mapping(raw, expected):
    session = FakeSession(FakeResponse({"status": raw, "content": {"video_url": "u"}}))
    vm = DoubaoVideoModel(_cfg("doubao", "http://gw/d", "seedance"), session=session)
    assert vm.poll("cgt-1").state == expected


def test_doubao_poll_surfaces_error_message():
    session = FakeSession(FakeResponse({"status": "failed", "error": {"message": "nsfw"}}))
    vm = DoubaoVideoModel(_cfg("doubao", "http://gw/d", "seedance"), session=session)
    status = vm.poll("cgt-1")
    assert status.state == "failed"
    assert status.error == "nsfw"


# ── 阿里 通义万相 ─────────────────────────────────────────────────────────────

def test_ali_submit_uses_async_header_and_legacy_size():
    session = FakeSession(FakeResponse({"output": {"task_id": "t-1"}}))
    vm = AliVideoModel(_cfg("ali", "http://gw/alivideo", "wan2.5-t2v-preview"), session=session)

    task_id = vm.submit(VideoRequest(prompt="p", ratio="9:16", resolution="720p", duration=5))

    assert task_id == "t-1"
    call = session.calls[0]
    assert call["url"] == (
        "http://gw/alivideo/api/v1/services/aigc/video-generation/video-synthesis"
    )
    assert call["headers"]["X-DashScope-Async"] == "enable"
    params = call["json"]["parameters"]
    assert params["size"] == "720*1280"
    assert "resolution" not in params


def test_ali_wan27_dialect_uses_resolution_and_ratio():
    session = FakeSession(FakeResponse({"output": {"task_id": "t-2"}}))
    vm = AliVideoModel(_cfg("ali", "http://gw/a", "wan2.7-t2v"), session=session)
    vm.submit(VideoRequest(prompt="p", ratio="16:9", resolution="1080p"))
    params = session.calls[0]["json"]["parameters"]
    assert params["resolution"] == "1080P"
    assert params["ratio"] == "16:9"
    assert "size" not in params


def test_ali_protocol_can_be_forced_to_legacy():
    session = FakeSession(FakeResponse({"output": {"task_id": "t"}}))
    vm = AliVideoModel(_cfg("ali", "http://gw/a", "wan2.7-t2v", PROTOCOL="legacy"), session=session)
    vm.submit(VideoRequest(prompt="p", ratio="16:9", resolution="1080p"))
    assert session.calls[0]["json"]["parameters"]["size"] == "1920*1080"


def test_ali_legacy_rejects_unknown_size_combination_without_fallback():
    session = FakeSession(FakeResponse({"output": {"task_id": "t"}}))
    vm = AliVideoModel(_cfg("ali", "http://gw/a", "wan2.5"), session=session)
    with pytest.raises(VideoGenError, match="unsupported legacy size combination"):
        vm.submit(VideoRequest(prompt="p", ratio="21:9", resolution="480p"))
    assert session.calls == []


def test_ali_negative_prompt_goes_into_input():
    session = FakeSession(FakeResponse({"output": {"task_id": "t"}}))
    vm = AliVideoModel(_cfg("ali", "http://gw/a", "wan2.5"), session=session)
    vm.submit(VideoRequest(prompt="p", negative_prompt="水印"))
    assert session.calls[0]["json"]["input"]["negative_prompt"] == "水印"


def test_ali_submit_without_task_id_raises():
    session = FakeSession(FakeResponse({"code": "Throttling", "message": "slow down"}))
    vm = AliVideoModel(_cfg("ali", "http://gw/a", "wan2.5"), session=session)
    with pytest.raises(VideoGenError, match="Throttling"):
        vm.submit(VideoRequest(prompt="p"))


def test_ali_task_url_appends_placeholder_when_missing():
    session = FakeSession(FakeResponse({"output": {"task_status": "RUNNING"}}))
    vm = AliVideoModel(_cfg("ali", "http://gw/a", "wan2.5", TASK_PATH="/v2/tasks"), session=session)
    vm.poll("abc")
    assert session.calls[0]["url"] == "http://gw/a/v2/tasks/abc"


@pytest.mark.parametrize(
    "raw,expected",
    [("PENDING", "pending"), ("RUNNING", "running"), ("SUCCEEDED", "succeeded"),
     ("FAILED", "failed"), ("CANCELED", "failed"), ("UNKNOWN", "failed"), ("WAT", "running")],
)
def test_ali_state_mapping(raw, expected):
    session = FakeSession(FakeResponse({"output": {"task_status": raw}}))
    vm = AliVideoModel(_cfg("ali", "http://gw/a", "wan2.5"), session=session)
    assert vm.poll("t").state == expected


def test_ali_poll_returns_video_url_on_success():
    session = FakeSession(
        FakeResponse({"output": {"task_status": "SUCCEEDED", "video_url": "https://cdn/v.mp4"}})
    )
    vm = AliVideoModel(_cfg("ali", "http://gw/a", "wan2.5"), session=session)
    assert vm.poll("t").video_url == "https://cdn/v.mp4"


# ── Google Veo / Vertex ───────────────────────────────────────────────────────

def test_vertex_requires_project_in_the_resource_path():
    """Vertex's resource path is meaningless without a project — no gateway shortcut."""
    vm = VertexVideoModel(_cfg("vertex", "http://gw/vertexvideo", "veo-3.1"))
    with pytest.raises(VideoGenError, match="VERTEX_VIDEO_PROJECT is required"):
        vm.submit(VideoRequest(prompt="p"))


def test_vertex_path_includes_project_and_location():
    session = FakeSession(FakeResponse({"name": "operations/op-1"}))
    vm = VertexVideoModel(
        _cfg("vertex", "http://gw/vertexvideo", "veo-3.1", PROJECT="my-proj", LOCATION="us-central1"),
        session=session,
    )

    op = vm.submit(VideoRequest(prompt="p", ratio="16:9", resolution="1080p", duration=6))

    assert op == "operations/op-1"
    assert session.calls[0]["url"] == (
        "http://gw/vertexvideo/v1/projects/my-proj/locations/us-central1"
        "/publishers/google/models/veo-3.1:predictLongRunning"
    )
    params = session.calls[0]["json"]["parameters"]
    assert params["durationSeconds"] == 6
    assert params["aspectRatio"] == "16:9"
    assert params["sampleCount"] == 1


def test_vertex_model_path_override_skips_project_requirement():
    session = FakeSession(FakeResponse({"name": "op"}))
    vm = VertexVideoModel(
        _cfg("vertex", "http://gw/v", "veo-3.1", MODEL_PATH="custom/path/model"), session=session
    )
    vm.submit(VideoRequest(prompt="p"))
    assert session.calls[0]["url"] == "http://gw/v/v1/custom/path/model:predictLongRunning"


def test_vertex_preserves_ratio_for_preflight_to_validate():
    session = FakeSession(FakeResponse({"name": "op"}))
    vm = VertexVideoModel(_cfg("vertex", "http://gw/v", "veo-3.1", PROJECT="p"), session=session)
    vm.submit(VideoRequest(prompt="p", ratio="1:1"))
    assert session.calls[0]["json"]["parameters"]["aspectRatio"] == "1:1"


def test_vertex_submit_without_operation_name_raises():
    session = FakeSession(FakeResponse({"error": {"message": "CONSUMER_INVALID"}}))
    vm = VertexVideoModel(_cfg("vertex", "http://gw/v", "veo-3.1", PROJECT="p"), session=session)
    with pytest.raises(VideoGenError, match="no operation name"):
        vm.submit(VideoRequest(prompt="p"))


def test_vertex_poll_running_until_done():
    session = FakeSession(FakeResponse({"done": False}))
    vm = VertexVideoModel(_cfg("vertex", "http://gw/v", "veo-3.1", PROJECT="p"), session=session)
    status = vm.poll("operations/op-1")
    assert status.state == "running"
    assert session.calls[0]["url"].endswith(":fetchPredictOperation")
    assert session.calls[0]["json"] == {"operationName": "operations/op-1"}


def test_vertex_poll_success_reads_gcs_uri():
    session = FakeSession(
        FakeResponse({"done": True, "response": {"videos": [{"gcsUri": "gs://b/v.mp4"}]}})
    )
    vm = VertexVideoModel(_cfg("vertex", "http://gw/v", "veo-3.1", PROJECT="p"), session=session)
    status = vm.poll("op")
    assert status.state == "succeeded"
    assert status.video_url == "gs://b/v.mp4"


def test_vertex_poll_success_reads_inline_base64():
    session = FakeSession(
        FakeResponse({"done": True, "response": {"videos": [{"bytesBase64Encoded": "AAAA"}]}})
    )
    vm = VertexVideoModel(_cfg("vertex", "http://gw/v", "veo-3.1", PROJECT="p"), session=session)
    assert vm.poll("op").video_b64 == "AAAA"


def test_vertex_poll_reports_rai_filter_reason():
    session = FakeSession(
        FakeResponse({"done": True,
                      "response": {"videos": [], "raiMediaFilteredReasons": ["blocked: violence"]}})
    )
    vm = VertexVideoModel(_cfg("vertex", "http://gw/v", "veo-3.1", PROJECT="p"), session=session)
    status = vm.poll("op")
    assert status.state == "failed"
    assert "violence" in status.error


def test_vertex_poll_surfaces_operation_error():
    session = FakeSession(FakeResponse({"error": {"message": "PERMISSION_DENIED"}}))
    vm = VertexVideoModel(_cfg("vertex", "http://gw/v", "veo-3.1", PROJECT="p"), session=session)
    status = vm.poll("op")
    assert status.state == "failed"
    assert status.error == "PERMISSION_DENIED"


# ── shared request plumbing ───────────────────────────────────────────────────

def test_http_error_becomes_video_gen_error():
    session = FakeSession(FakeResponse({}, status_code=503, text="upstream down"))
    vm = AliVideoModel(_cfg("ali", "http://gw/a", "wan2.5"), session=session)
    with pytest.raises(VideoGenError, match="HTTP 503"):
        vm.submit(VideoRequest(prompt="p"))


def test_non_json_response_becomes_video_gen_error():
    session = FakeSession(FakeResponse(_NOT_JSON, text="<html>gateway</html>"))
    vm = AliVideoModel(_cfg("ali", "http://gw/a", "wan2.5"), session=session)
    with pytest.raises(VideoGenError, match="non-JSON"):
        vm.submit(VideoRequest(prompt="p"))


def test_request_exception_becomes_video_gen_error():
    import requests

    class ExplodingSession:
        def request(self, *a, **k):
            raise requests.ConnectionError("dns")

    vm = AliVideoModel(_cfg("ali", "http://gw/a", "wan2.5"), session=ExplodingSession())
    with pytest.raises(VideoGenError, match="request to .* failed"):
        vm.submit(VideoRequest(prompt="p"))


# ── VideoModel.download ───────────────────────────────────────────────────────

class FakeStreamResponse:
    """A context-manager response for `session.get(..., stream=True)`."""

    def __init__(self, chunks, status_code=200):
        self._chunks = chunks
        self.status_code = status_code

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")

    def iter_content(self, chunk_size=None):
        yield from self._chunks


class FakeGetSession:
    """Only implements the `.get(url, stream=True, timeout=...)` path download() uses."""

    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self.response


def test_download_streams_an_https_url(tmp_path):
    session = FakeGetSession(FakeStreamResponse([b"abc", b"def"]))
    vm = DoubaoVideoModel(_cfg("doubao", "http://gw/d", "seedance"), session=session)
    status = TaskStatus(state="succeeded", raw={}, video_url="https://cdn.example.com/v.mp4")

    dest = tmp_path / "out.mp4"
    result = vm.download(status, dest)

    assert result == dest
    assert dest.read_bytes() == b"abcdef"
    assert session.calls[0]["url"] == "https://cdn.example.com/v.mp4"
    assert session.calls[0]["stream"] is True


def test_download_rewrites_gs_url_before_streaming(tmp_path):
    session = FakeGetSession(FakeStreamResponse([b"payload"]))
    vm = DoubaoVideoModel(_cfg("doubao", "http://gw/d", "seedance"), session=session)
    status = TaskStatus(state="succeeded", raw={}, video_url="gs://my-bucket/videos/v.mp4")

    dest = tmp_path / "out.mp4"
    vm.download(status, dest)

    assert session.calls[0]["url"] == "https://storage.googleapis.com/my-bucket/videos/v.mp4"
    assert dest.read_bytes() == b"payload"


def test_download_creates_missing_parent_directories(tmp_path):
    session = FakeGetSession(FakeStreamResponse([b"x"]))
    vm = DoubaoVideoModel(_cfg("doubao", "http://gw/d", "seedance"), session=session)
    status = TaskStatus(state="succeeded", raw={}, video_url="https://cdn/v.mp4")

    dest = tmp_path / "nested" / "dir" / "out.mp4"
    vm.download(status, dest)

    assert dest.exists()


def test_download_decodes_inline_base64_without_any_http_call(tmp_path):
    import base64

    session = FakeGetSession(FakeStreamResponse([b"should never be read"]))
    vm = DoubaoVideoModel(_cfg("doubao", "http://gw/d", "seedance"), session=session)
    payload = base64.b64encode(b"raw video bytes").decode()
    status = TaskStatus(state="succeeded", raw={}, video_b64=payload)

    dest = tmp_path / "out.mp4"
    vm.download(status, dest)

    assert dest.read_bytes() == b"raw video bytes"
    assert session.calls == []  # no HTTP call for the base64 path


def test_download_raises_when_neither_url_nor_b64_is_present(tmp_path):
    session = FakeGetSession(FakeStreamResponse([]))
    vm = DoubaoVideoModel(_cfg("doubao", "http://gw/d", "seedance"), session=session)
    status = TaskStatus(state="succeeded", raw={})

    with pytest.raises(VideoGenError, match="without a video payload"):
        vm.download(status, tmp_path / "out.mp4")
