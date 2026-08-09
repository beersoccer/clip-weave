"""Frozen, validated production-contract records.

This module intentionally contains only in-memory schema validation. Persistence,
revision ledgers, and pipeline integration belong to later layers.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from numbers import Real

from clip_weave.adapters.video_gen import VideoGenError


def _text(value: object, field: str, *, allow_none: bool = False) -> None:
    if value is None and allow_none:
        return
    if not isinstance(value, str) or not value.strip():
        raise VideoGenError(f"{field} must be a non-empty string")


def _text_tuple(value: object, field: str) -> None:
    if not isinstance(value, tuple):
        raise VideoGenError(f"{field} must be a tuple of non-empty strings")
    for item in value:
        _text(item, field)


def _choice(value: object, field: str, choices: set[str], *, allow_none: bool = False) -> None:
    if value is None and allow_none:
        return
    if not isinstance(value, str):
        raise VideoGenError(f"{field} must be a string")
    try:
        is_allowed = value in choices
    except TypeError as exc:
        raise VideoGenError(f"{field} must be a hashable string") from exc
    if not is_allowed:
        allowed = ", ".join(sorted(choices))
        raise VideoGenError(f"{field} must be one of: {allowed}")


def _positive(value: object, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value) or value <= 0:
        raise VideoGenError(f"{field} must be greater than 0")


def _unit_interval(value: object, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value) or not 0 <= value <= 1:
        raise VideoGenError(f"{field} must be between 0 and 1")


def _positive_int(value: object, field: str) -> None:
    if type(value) is not int or value <= 0:
        raise VideoGenError(f"{field} must be a positive integer")


@dataclass(frozen=True)
class CreativeContract:
    production_profile: str
    audience: str
    platform: str
    target_duration_seconds: float
    narrative_promise: str
    must_keep: tuple[str, ...]
    must_not: tuple[str, ...]

    def __post_init__(self) -> None:
        _choice(self.production_profile, "production_profile", {"html_launch", "t2v_brand_film"})
        _text(self.audience, "audience")
        _text(self.platform, "platform")
        _positive(self.target_duration_seconds, "target_duration_seconds")
        _text(self.narrative_promise, "narrative_promise")
        _text_tuple(self.must_keep, "must_keep")
        _text_tuple(self.must_not, "must_not")


@dataclass(frozen=True)
class FactSource:
    id: str
    claim: str
    source: str
    approved: bool

    def __post_init__(self) -> None:
        _text(self.id, "id")
        _text(self.claim, "claim")
        _text(self.source, "source")
        if type(self.approved) is not bool:
            raise VideoGenError("approved must be a bool")


@dataclass(frozen=True)
class ReferenceAudit:
    audit_id: str
    shot_id: str
    subject_type: str
    requirement: str | None
    requested: str | None
    submitted: str | None
    applied: str | None
    outcome: str
    reason: str | None
    proof_media_ref: str | None

    def __post_init__(self) -> None:
        _text(self.audit_id, "audit_id")
        _text(self.shot_id, "shot_id")
        _choice(
            self.subject_type,
            "subject_type",
            {"product", "person", "scene", "style", "first_frame", "last_frame", "proof_media"},
        )
        _choice(self.requirement, "requirement", {"optional", "required"}, allow_none=True)
        _text(self.requested, "requested", allow_none=True)
        _text(self.submitted, "submitted", allow_none=True)
        _text(self.applied, "applied", allow_none=True)
        _choice(self.outcome, "outcome", {"not_requested", "accepted", "dropped", "blocked"})
        _text(self.reason, "reason", allow_none=True)
        _text(self.proof_media_ref, "proof_media_ref", allow_none=True)
        if self.outcome == "accepted":
            if self.requested is None:
                raise VideoGenError("requested is required when outcome is accepted")
            if self.applied is None:
                raise VideoGenError("applied is required when outcome is accepted")
        if self.outcome in {"dropped", "blocked"} and self.reason is None:
            raise VideoGenError(f"reason is required when outcome is {self.outcome}")


@dataclass(frozen=True)
class ShotCard:
    shot_id: str
    purpose: str
    subject: str
    action: str
    scene: str
    camera: str
    lighting: str
    duration_seconds: float
    must_keep: tuple[str, ...]
    must_not: tuple[str, ...]
    reference_audit_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        for field in ("shot_id", "purpose", "subject", "action", "scene", "camera", "lighting"):
            _text(getattr(self, field), field)
        _positive(self.duration_seconds, "duration_seconds")
        _text_tuple(self.must_keep, "must_keep")
        _text_tuple(self.must_not, "must_not")
        _text_tuple(self.reference_audit_refs, "reference_audit_refs")


@dataclass(frozen=True)
class Cue:
    cue_id: str
    start_seconds: float
    end_seconds: float
    kind: str
    content: str
    shot_id: str

    def __post_init__(self) -> None:
        _text(self.cue_id, "cue_id")
        if (
            isinstance(self.start_seconds, bool)
            or isinstance(self.end_seconds, bool)
            or not isinstance(self.start_seconds, Real)
            or not isinstance(self.end_seconds, Real)
            or not isfinite(self.start_seconds)
            or not isfinite(self.end_seconds)
            or self.start_seconds < 0
            or self.start_seconds > self.end_seconds
        ):
            raise VideoGenError("start_seconds and end_seconds must satisfy 0 <= start_seconds <= end_seconds")
        _choice(self.kind, "kind", {"vo", "sfx", "caption", "cta", "transition", "hold"})
        _text(self.content, "content")
        _text(self.shot_id, "shot_id")


@dataclass(frozen=True)
class ReviewDecision:
    target_type: str
    target_id: str
    target_revision: int
    decision: str
    reasons: tuple[str, ...]
    score: float
    confidence: float
    reviewer: str
    reviewed_at: str

    def __post_init__(self) -> None:
        for field in ("target_type", "target_id", "reviewer", "reviewed_at"):
            _text(getattr(self, field), field)
        _positive_int(self.target_revision, "target_revision")
        _choice(self.decision, "decision", {"accepted", "revise", "rejected"})
        _text_tuple(self.reasons, "reasons")
        _unit_interval(self.score, "score")
        _unit_interval(self.confidence, "confidence")


def _unique_ids(records: tuple[object, ...], attribute: str, field: str) -> set[str]:
    ids = [getattr(record, attribute) for record in records]
    if len(ids) != len(set(ids)):
        raise VideoGenError(f"{field} contains duplicate {attribute} values")
    return set(ids)


@dataclass(frozen=True)
class ProductionContract:
    creative_contract: CreativeContract
    facts_sources: tuple[FactSource, ...]
    reference_audits: tuple[ReferenceAudit, ...]
    shot_cards: tuple[ShotCard, ...]
    cue_sheet: tuple[Cue, ...]
    review_decisions: tuple[ReviewDecision, ...]

    def __post_init__(self) -> None:
        if type(self.creative_contract) is not CreativeContract:
            raise VideoGenError("creative_contract must be a CreativeContract")
        collections: tuple[tuple[str, tuple[object, ...], type[object]], ...] = (
            ("facts_sources", self.facts_sources, FactSource),
            ("reference_audits", self.reference_audits, ReferenceAudit),
            ("shot_cards", self.shot_cards, ShotCard),
            ("cue_sheet", self.cue_sheet, Cue),
            ("review_decisions", self.review_decisions, ReviewDecision),
        )
        for field, records, expected_type in collections:
            if not isinstance(records, tuple):
                raise VideoGenError(f"{field} must be a tuple")
            if any(type(record) is not expected_type for record in records):
                raise VideoGenError(f"{field} must contain only {expected_type.__name__}")
        _unique_ids(self.facts_sources, "id", "facts_sources")
        audit_ids = _unique_ids(self.reference_audits, "audit_id", "reference_audits")
        shot_ids = _unique_ids(self.shot_cards, "shot_id", "shot_cards")
        _unique_ids(self.cue_sheet, "cue_id", "cue_sheet")
        _unique_ids(self.review_decisions, "target_id", "review_decisions")
        for shot in self.shot_cards:
            for audit_id in shot.reference_audit_refs:
                if audit_id not in audit_ids:
                    raise VideoGenError(f"reference_audit_refs contains unknown audit_id {audit_id}")
        for item in self.cue_sheet:
            if item.shot_id not in shot_ids:
                raise VideoGenError(f"cue shot_id references unknown shot {item.shot_id}")
