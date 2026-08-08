"""Pure validation and normalization for video-generation requests."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal
from urllib.parse import urlparse

from clip_weave.adapters.video_gen import ProviderCapabilities, VideoGenError, VideoRequest


ReferenceRequirement = Literal["optional", "required"]
ReferenceOutcome = Literal["not_requested", "accepted", "dropped", "blocked"]


@dataclass(frozen=True)
class ReferenceAudit:
    requested: str | None
    requirement: ReferenceRequirement | None
    outcome: ReferenceOutcome
    applied: str | None
    reason: str | None


@dataclass(frozen=True)
class PreflightResult:
    request: VideoRequest
    requested_parameters: dict[str, object]
    applied_parameters: dict[str, object]
    reference_audit: ReferenceAudit


def _validate_capabilities(request: VideoRequest, capabilities: ProviderCapabilities) -> None:
    if capabilities.ratios and request.ratio not in capabilities.ratios:
        raise VideoGenError(
            f"unsupported ratio {request.ratio!r}; supported ratios: {sorted(capabilities.ratios)!r}"
        )
    if capabilities.resolutions and request.resolution not in capabilities.resolutions:
        raise VideoGenError(
            f"unsupported resolution {request.resolution!r}; "
            f"supported resolutions: {sorted(capabilities.resolutions)!r}"
        )
    if (
        capabilities.supported_resolution_ratios is not None
        and (request.resolution, request.ratio) not in capabilities.supported_resolution_ratios
    ):
        raise VideoGenError(
            f"unsupported resolution/ratio ({request.resolution!r}, {request.ratio!r}); "
            f"supported resolution/ratio combinations: {sorted(capabilities.supported_resolution_ratios)!r}"
        )


def _clamp_duration(duration: int, capabilities: ProviderCapabilities) -> int:
    seconds = duration or capabilities.duration_range[0]
    if capabilities.duration_choices:
        return min(capabilities.duration_choices, key=lambda choice: abs(choice - seconds))
    lower, upper = capabilities.duration_range
    return int(max(lower, min(upper, round(seconds))))


def _audit_reference(
    reference: str | None,
    requirement: ReferenceRequirement | None,
    capabilities: ProviderCapabilities,
) -> ReferenceAudit:
    if not reference:
        return ReferenceAudit(None, None, "not_requested", None, None)

    effective_requirement: ReferenceRequirement = requirement or "optional"
    try:
        parsed = urlparse(reference)
        scheme = parsed.scheme.lower()
        parsed.port
    except ValueError as error:
        raise VideoGenError(
            f"{effective_requirement} reference {reference!r} cannot be parsed: {error}"
        ) from error
    if scheme in capabilities.reference_uri_schemes:
        return ReferenceAudit(reference, effective_requirement, "accepted", reference, None)

    if scheme:
        reason = f"reference URI scheme {scheme!r} is not supported"
    else:
        reason = "local reference is not materialized"
    if effective_requirement == "required":
        raise VideoGenError(f"required reference {reference!r} cannot be used: {reason}")
    return ReferenceAudit(reference, effective_requirement, "dropped", None, reason)


def preflight_request(
    request: VideoRequest,
    capabilities: ProviderCapabilities,
    *,
    reference: str | None,
    reference_requirement: ReferenceRequirement | None,
) -> PreflightResult:
    """Validate provider constraints and produce an auditable request without I/O."""
    if reference_requirement not in (None, "optional", "required"):
        raise VideoGenError(f"invalid reference requirement {reference_requirement!r}")

    _validate_capabilities(request, capabilities)
    duration = _clamp_duration(request.duration, capabilities)
    audit = _audit_reference(reference, reference_requirement, capabilities)
    requested_parameters: dict[str, object] = {
        "ratio": request.ratio,
        "resolution": request.resolution,
        "duration": request.duration,
        "negative_prompt": request.negative_prompt,
        "seed": request.seed,
        "generate_audio": request.generate_audio,
        "watermark": request.watermark,
    }
    applied_parameters = {**requested_parameters, "duration": duration}
    return PreflightResult(
        request=replace(request, duration=duration, image_url=audit.applied),
        requested_parameters=requested_parameters,
        applied_parameters=applied_parameters,
        reference_audit=audit,
    )
