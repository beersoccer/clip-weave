"""Frozen, validated production-contract records and their v1 revision ledger."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from math import isfinite
import os
from pathlib import Path
import tempfile

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


def _json_number(value: object) -> bool:
    return type(value) in {int, float} and isfinite(value)


def _positive(value: object, field: str) -> None:
    if not _json_number(value) or value <= 0:
        raise VideoGenError(f"{field} must be greater than 0")


def _unit_interval(value: object, field: str) -> None:
    if not _json_number(value) or not 0 <= value <= 1:
        raise VideoGenError(f"{field} must be between 0 and 1")


def _positive_int(value: object, field: str) -> None:
    if type(value) is not int or value <= 0:
        raise VideoGenError(f"{field} must be a positive integer")


@dataclass(frozen=True)
class CreativeContract:
    production_profile: str
    audience: str
    platform: str
    target_duration_seconds: int
    narrative_promise: str
    must_keep: tuple[str, ...]
    must_not: tuple[str, ...]

    def __post_init__(self) -> None:
        _choice(self.production_profile, "production_profile", {"html_launch", "t2v_brand_film"})
        _text(self.audience, "audience")
        _text(self.platform, "platform")
        _positive_int(self.target_duration_seconds, "target_duration_seconds")
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
            not _json_number(self.start_seconds)
            or not _json_number(self.end_seconds)
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


def _unique_ids(records: tuple[object, ...], attribute: str, field: str) -> tuple[str, ...]:
    ids: list[str] = []
    for record in records:
        identifier = getattr(record, attribute)
        if identifier in ids:
            raise VideoGenError(f"{field} contains duplicate {attribute} values")
        ids.append(identifier)
    return tuple(ids)


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
        for shot in self.shot_cards:
            for audit_id in shot.reference_audit_refs:
                if audit_id not in audit_ids:
                    raise VideoGenError(f"reference_audit_refs contains unknown audit_id {audit_id}")
        for item in self.cue_sheet:
            if item.shot_id not in shot_ids:
                raise VideoGenError(f"cue shot_id references unknown shot {item.shot_id}")


@dataclass(frozen=True)
class ContractRevision:
    revision: int
    created_at: str
    reason: str
    contract: ProductionContract

    def __post_init__(self) -> None:
        _positive_int(self.revision, "revision")
        _text(self.created_at, "created_at")
        _text(self.reason, "reason")
        if type(self.contract) is not ProductionContract:
            raise VideoGenError("contract must be a ProductionContract")


_LEDGER_SCHEMA_VERSION = 1
_LEDGER_FILE_NAME = "production-contract.json"


def _ledger_path(project_dir: Path) -> Path:
    return project_dir / "renders" / _LEDGER_FILE_NAME


def _mapping(value: object, context: str, keys: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise VideoGenError(f"{context} has invalid fields")
    return value


def _list(value: object, context: str) -> list[object]:
    if not isinstance(value, list):
        raise VideoGenError(f"{context} must be a list")
    return value


def _tuple_of_text(value: object, context: str) -> tuple[str, ...]:
    values = _list(value, context)
    if any(not isinstance(item, str) for item in values):
        raise VideoGenError(f"{context} must contain strings")
    return tuple(values)


def _record_to_dict(record: object) -> dict[str, object]:
    if type(record) is CreativeContract:
        item = record
        return {
            "production_profile": item.production_profile,
            "audience": item.audience,
            "platform": item.platform,
            "target_duration_seconds": item.target_duration_seconds,
            "narrative_promise": item.narrative_promise,
            "must_keep": list(item.must_keep),
            "must_not": list(item.must_not),
        }
    if type(record) is FactSource:
        item = record
        return {"id": item.id, "claim": item.claim, "source": item.source, "approved": item.approved}
    if type(record) is ReferenceAudit:
        item = record
        return {
            "audit_id": item.audit_id,
            "shot_id": item.shot_id,
            "subject_type": item.subject_type,
            "requirement": item.requirement,
            "requested": item.requested,
            "submitted": item.submitted,
            "applied": item.applied,
            "outcome": item.outcome,
            "reason": item.reason,
            "proof_media_ref": item.proof_media_ref,
        }
    if type(record) is ShotCard:
        item = record
        return {
            "shot_id": item.shot_id,
            "purpose": item.purpose,
            "subject": item.subject,
            "action": item.action,
            "scene": item.scene,
            "camera": item.camera,
            "lighting": item.lighting,
            "duration_seconds": item.duration_seconds,
            "must_keep": list(item.must_keep),
            "must_not": list(item.must_not),
            "reference_audit_refs": list(item.reference_audit_refs),
        }
    if type(record) is Cue:
        item = record
        return {
            "cue_id": item.cue_id,
            "start_seconds": item.start_seconds,
            "end_seconds": item.end_seconds,
            "kind": item.kind,
            "content": item.content,
            "shot_id": item.shot_id,
        }
    if type(record) is ReviewDecision:
        item = record
        return {
            "target_type": item.target_type,
            "target_id": item.target_id,
            "target_revision": item.target_revision,
            "decision": item.decision,
            "reasons": list(item.reasons),
            "score": item.score,
            "confidence": item.confidence,
            "reviewer": item.reviewer,
            "reviewed_at": item.reviewed_at,
        }
    raise VideoGenError("unsupported contract record")


def _contract_to_dict(contract: ProductionContract) -> dict[str, object]:
    return {
        "creative_contract": _record_to_dict(contract.creative_contract),
        "facts_sources": [_record_to_dict(item) for item in contract.facts_sources],
        "reference_audits": [_record_to_dict(item) for item in contract.reference_audits],
        "shot_cards": [_record_to_dict(item) for item in contract.shot_cards],
        "cue_sheet": [_record_to_dict(item) for item in contract.cue_sheet],
        "review_decisions": [_record_to_dict(item) for item in contract.review_decisions],
    }


def _contract_from_dict(value: object) -> ProductionContract:
    data = _mapping(value, "contract", {"creative_contract", "facts_sources", "reference_audits", "shot_cards", "cue_sheet", "review_decisions"})
    creative = _mapping(data["creative_contract"], "creative_contract", {"production_profile", "audience", "platform", "target_duration_seconds", "narrative_promise", "must_keep", "must_not"})
    facts = _list(data["facts_sources"], "facts_sources")
    audits = _list(data["reference_audits"], "reference_audits")
    shots = _list(data["shot_cards"], "shot_cards")
    cues = _list(data["cue_sheet"], "cue_sheet")
    decisions = _list(data["review_decisions"], "review_decisions")
    return ProductionContract(
        creative_contract=CreativeContract(
            creative["production_profile"], creative["audience"], creative["platform"], creative["target_duration_seconds"],
            creative["narrative_promise"], _tuple_of_text(creative["must_keep"], "creative_contract.must_keep"), _tuple_of_text(creative["must_not"], "creative_contract.must_not"),
        ),
        facts_sources=tuple(FactSource(**_mapping(item, "facts_sources item", {"id", "claim", "source", "approved"})) for item in facts),
        reference_audits=tuple(ReferenceAudit(**_mapping(item, "reference_audits item", {"audit_id", "shot_id", "subject_type", "requirement", "requested", "submitted", "applied", "outcome", "reason", "proof_media_ref"})) for item in audits),
        shot_cards=tuple(_shot_card_from_dict(item) for item in shots),
        cue_sheet=tuple(Cue(**_mapping(item, "cue_sheet item", {"cue_id", "start_seconds", "end_seconds", "kind", "content", "shot_id"})) for item in cues),
        review_decisions=tuple(_review_decision_from_dict(item) for item in decisions),
    )


def _shot_card_from_dict(value: object) -> ShotCard:
    data = _mapping(value, "shot_cards item", {"shot_id", "purpose", "subject", "action", "scene", "camera", "lighting", "duration_seconds", "must_keep", "must_not", "reference_audit_refs"})
    return ShotCard(
        data["shot_id"], data["purpose"], data["subject"], data["action"], data["scene"], data["camera"], data["lighting"], data["duration_seconds"],
        _tuple_of_text(data["must_keep"], "shot_cards.must_keep"), _tuple_of_text(data["must_not"], "shot_cards.must_not"), _tuple_of_text(data["reference_audit_refs"], "shot_cards.reference_audit_refs"),
    )


def _review_decision_from_dict(value: object) -> ReviewDecision:
    data = _mapping(value, "review_decisions item", {"target_type", "target_id", "target_revision", "decision", "reasons", "score", "confidence", "reviewer", "reviewed_at"})
    return ReviewDecision(
        data["target_type"], data["target_id"], data["target_revision"], data["decision"], _tuple_of_text(data["reasons"], "review_decisions.reasons"),
        data["score"], data["confidence"], data["reviewer"], data["reviewed_at"],
    )


def _revision_to_dict(record: ContractRevision) -> dict[str, object]:
    return {"revision": record.revision, "created_at": record.created_at, "reason": record.reason, "contract": _contract_to_dict(record.contract)}


def _revision_from_dict(value: object) -> ContractRevision:
    data = _mapping(value, "revision", {"revision", "created_at", "reason", "contract"})
    return ContractRevision(data["revision"], data["created_at"], data["reason"], _contract_from_dict(data["contract"]))


def _decode_ledger(value: object) -> list[ContractRevision]:
    data = _mapping(value, "ledger", {"schema_version", "current_revision", "revisions"})
    if type(data["schema_version"]) is not int or data["schema_version"] != _LEDGER_SCHEMA_VERSION:
        raise VideoGenError("unsupported ledger schema_version")
    if type(data["current_revision"]) is not int or data["current_revision"] <= 0:
        raise VideoGenError("current_revision must be a positive integer")
    records = [_revision_from_dict(item) for item in _list(data["revisions"], "revisions")]
    if not records:
        raise VideoGenError("revisions must not be empty")
    if [record.revision for record in records] != list(range(1, len(records) + 1)):
        raise VideoGenError("revisions must be continuous from 1")
    if data["current_revision"] != records[-1].revision:
        raise VideoGenError("current_revision must point to the last revision")
    return records


def _read_ledger(path: Path) -> list[ContractRevision]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return _decode_ledger(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, VideoGenError) as exc:
        raise VideoGenError(f"{path}: invalid production contract ledger: {exc}") from exc


def _write_ledger_atomically(path: Path, payload: dict[str, object]) -> None:
    temporary_path: str | None = None
    replacement_completed = False
    write_error: OSError | None = None
    cleanup_error: OSError | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
            prefix=".production-contract-",
            suffix=".tmp",
        ) as temporary_file:
            temporary_path = temporary_file.name
            json.dump(payload, temporary_file, ensure_ascii=False, indent=2)
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
        replacement_completed = True
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as exc:
        write_error = exc
    finally:
        try:
            if temporary_path is not None and os.path.exists(temporary_path):
                Path(temporary_path).unlink()
        except OSError as exc:
            cleanup_error = exc
    if write_error is not None:
        if replacement_completed:
            raise VideoGenError(
                f"{path}: replacement completed, but unable to sync production contract ledger directory: {write_error}"
            ) from write_error
        raise write_error
    if cleanup_error is not None:
        raise VideoGenError(f"{path}: unable to clean up temporary production contract ledger: {cleanup_error}") from cleanup_error


def load_current_contract(project_dir: Path) -> ProductionContract | None:
    path = _ledger_path(project_dir)
    if not path.exists():
        return None
    return _read_ledger(path)[-1].contract


def load_contract_revision(project_dir: Path, revision: int) -> ProductionContract:
    _positive_int(revision, "revision")
    path = _ledger_path(project_dir)
    if not path.exists():
        raise VideoGenError(f"{path}: revision {revision} does not exist")
    for record in _read_ledger(path):
        if record.revision == revision:
            return record.contract
    raise VideoGenError(f"{path}: revision {revision} does not exist")


def append_contract_revision(project_dir: Path, contract: ProductionContract, *, reason: str) -> ContractRevision:
    _text(reason, "reason")
    if type(contract) is not ProductionContract:
        raise VideoGenError("contract must be a ProductionContract")
    path = _ledger_path(project_dir)
    records = _read_ledger(path) if path.exists() else []
    record = ContractRevision(len(records) + 1, datetime.now(timezone.utc).isoformat(), reason, contract)
    all_records = [*records, record]
    _write_ledger_atomically(path, {"schema_version": _LEDGER_SCHEMA_VERSION, "current_revision": record.revision, "revisions": [_revision_to_dict(item) for item in all_records]})
    return record
