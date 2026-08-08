from __future__ import annotations

import pytest

from clip_weave.adapters.video_gen import ProviderCapabilities, VideoGenError, VideoRequest
from clip_weave.core.generation_preflight import preflight_request


def capabilities(**overrides: object) -> ProviderCapabilities:
    values: dict[str, object] = {
        "ratios": frozenset({"16:9", "9:16"}),
        "resolutions": frozenset({"720p", "1080p"}),
        "duration_range": (5, 10),
        "reference_uri_schemes": frozenset({"https"}),
    }
    values.update(overrides)
    return ProviderCapabilities(**values)  # type: ignore[arg-type]


def test_required_unsupported_reference_uri_is_blocked() -> None:
    with pytest.raises(VideoGenError, match=r"required reference.*gs://bucket/frame.png"):
        preflight_request(
            VideoRequest(prompt="city"),
            capabilities(),
            reference="gs://bucket/frame.png",
            reference_requirement="required",
        )


def test_optional_local_reference_is_dropped_without_materialization() -> None:
    result = preflight_request(
        VideoRequest(prompt="city"),
        capabilities(),
        reference="/tmp/frame.png",
        reference_requirement="optional",
    )

    assert result.request.image_url is None
    assert result.reference_audit.requested == "/tmp/frame.png"
    assert result.reference_audit.requirement == "optional"
    assert result.reference_audit.outcome == "dropped"
    assert result.reference_audit.applied is None
    assert result.reference_audit.reason == "local reference is not materialized"


def test_duration_is_clamped_and_audited() -> None:
    request = VideoRequest(
        prompt="city",
        duration=99,
        ratio="16:9",
        resolution="1080p",
        negative_prompt="no text",
        seed=7,
        generate_audio=True,
        watermark=True,
    )

    result = preflight_request(
        request,
        capabilities(),
        reference=None,
        reference_requirement=None,
    )

    assert result.request.duration == 10
    assert result.requested_parameters == {
        "ratio": "16:9",
        "resolution": "1080p",
        "duration": 99,
        "negative_prompt": "no text",
        "seed": 7,
        "generate_audio": True,
        "watermark": True,
    }
    assert result.applied_parameters == {**result.requested_parameters, "duration": 10}
    assert result.reference_audit.outcome == "not_requested"
    assert result.reference_audit.requirement is None
    assert result.reference_audit.applied is None
    assert result.reference_audit.reason is None


def test_accepted_https_reference_is_preserved() -> None:
    reference = "https://cdn.example/frame.png"

    result = preflight_request(
        VideoRequest(prompt="city"),
        capabilities(),
        reference=reference,
        reference_requirement=None,
    )

    assert result.request.image_url == reference
    assert result.reference_audit.requested == reference
    assert result.reference_audit.requirement == "optional"
    assert result.reference_audit.outcome == "accepted"
    assert result.reference_audit.applied == reference
    assert result.reference_audit.reason is None


@pytest.mark.parametrize(
    ("video_request", "match"),
    [
        (VideoRequest(prompt="city", ratio="1:1"), r"ratio.*1:1.*16:9"),
        (VideoRequest(prompt="city", resolution="4k"), r"resolution.*4k.*1080p"),
        (
            VideoRequest(prompt="city", resolution="1080p", ratio="9:16"),
            r"resolution.*ratio.*1080p.*9:16",
        ),
    ],
)
def test_unsupported_capability_parameter_is_rejected(video_request: VideoRequest, match: str) -> None:
    caps = capabilities(
        supported_resolution_ratios=frozenset({("720p", "9:16"), ("1080p", "16:9")}),
    )

    with pytest.raises(VideoGenError, match=match):
        preflight_request(video_request, caps, reference=None, reference_requirement=None)


def test_duration_choices_choose_earlier_value_on_a_tie() -> None:
    result = preflight_request(
        VideoRequest(prompt="city", duration=6),
        capabilities(duration_choices=(5, 7)),
        reference=None,
        reference_requirement=None,
    )

    assert result.request.duration == 5
    assert result.applied_parameters["duration"] == 5
