from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from clip_weave.adapters.video_gen import VideoGenError
from clip_weave.core.production_contract import (
    CreativeContract,
    Cue,
    FactSource,
    ProductionContract,
    ReferenceAudit,
    ReviewDecision,
    ShotCard,
)


def creative_contract(**overrides: object) -> CreativeContract:
    values: dict[str, object] = {
        "production_profile": "html_launch",
        "audience": "product leaders",
        "platform": "web",
        "target_duration_seconds": 30,
        "narrative_promise": "Show the product value clearly.",
        "must_keep": ("brand blue",),
        "must_not": ("unsupported claims",),
    }
    values.update(overrides)
    return CreativeContract(**values)  # type: ignore[arg-type]


def reference_audit(**overrides: object) -> ReferenceAudit:
    values: dict[str, object] = {
        "audit_id": "audit-1",
        "shot_id": "shot-1",
        "subject_type": "product",
        "requirement": "required",
        "requested": "product.png",
        "submitted": "gs://proof/product.png",
        "applied": "gs://proof/product.png",
        "outcome": "accepted",
        "reason": None,
        "proof_media_ref": "proof-1",
    }
    values.update(overrides)
    return ReferenceAudit(**values)  # type: ignore[arg-type]


def shot_card(**overrides: object) -> ShotCard:
    values: dict[str, object] = {
        "shot_id": "shot-1",
        "purpose": "Introduce the product.",
        "subject": "The product interface",
        "action": "opens to the dashboard",
        "scene": "dark studio",
        "camera": "slow dolly in",
        "lighting": "soft blue rim light",
        "duration_seconds": 5,
        "must_keep": ("logo",),
        "must_not": ("text glitches",),
        "reference_audit_refs": ("audit-1",),
    }
    values.update(overrides)
    return ShotCard(**values)  # type: ignore[arg-type]


def cue(**overrides: object) -> Cue:
    values: dict[str, object] = {
        "cue_id": "cue-1",
        "start_seconds": 0,
        "end_seconds": 3,
        "kind": "vo",
        "content": "A clearer way to launch.",
        "shot_id": "shot-1",
    }
    values.update(overrides)
    return Cue(**values)  # type: ignore[arg-type]


def review_decision(**overrides: object) -> ReviewDecision:
    values: dict[str, object] = {
        "target_type": "shot",
        "target_id": "shot-1",
        "target_revision": "rev-1",
        "decision": "accepted",
        "reasons": ("Matches the creative contract.",),
        "score": 0.9,
        "confidence": 0.8,
        "reviewer": "director",
        "reviewed_at": "2026-08-09T10:00:00+08:00",
    }
    values.update(overrides)
    return ReviewDecision(**values)  # type: ignore[arg-type]


def valid_contract(**overrides: object) -> ProductionContract:
    values: dict[str, object] = {
        "creative_contract": creative_contract(),
        "fact_sources": (
            FactSource(
                id="fact-1",
                claim="The product supports shared review.",
                source="approved product brief",
                approved=True,
            ),
        ),
        "reference_audits": (reference_audit(),),
        "shot_cards": (shot_card(),),
        "cues": (cue(),),
        "review_decisions": (review_decision(),),
    }
    values.update(overrides)
    return ProductionContract(**values)  # type: ignore[arg-type]


def test_valid_complete_snapshot_is_frozen() -> None:
    contract = valid_contract()

    assert contract.shot_cards[0].reference_audit_refs == ("audit-1",)
    assert contract.cues[0].shot_id == "shot-1"
    with pytest.raises(FrozenInstanceError):
        contract.creative_contract.audience = "another audience"  # type: ignore[misc]


def test_contract_rejects_dangling_reference_audit() -> None:
    with pytest.raises(VideoGenError, match=r"reference_audit_refs.*audit-missing"):
        valid_contract(shot_cards=(shot_card(reference_audit_refs=("audit-missing",)),))


@pytest.mark.parametrize(
    ("factory", "overrides", "field"),
    [
        (creative_contract, {"production_profile": "unknown"}, "production_profile"),
        (reference_audit, {"subject_type": "unknown"}, "subject_type"),
        (reference_audit, {"requirement": "unknown"}, "requirement"),
        (reference_audit, {"outcome": "unknown"}, "outcome"),
        (cue, {"kind": "unknown"}, "kind"),
        (review_decision, {"decision": "unknown"}, "decision"),
    ],
)
def test_unknown_enum_values_are_rejected(factory: object, overrides: dict[str, object], field: str) -> None:
    with pytest.raises(VideoGenError, match=field):
        factory(**overrides)  # type: ignore[operator]


@pytest.mark.parametrize(
    ("factory", "overrides", "field"),
    [
        (creative_contract, {"audience": ""}, "audience"),
        (creative_contract, {"must_keep": ("",)}, "must_keep"),
        (FactSource, {"id": "fact-1", "claim": "claim", "source": "brief", "approved": 1}, "approved"),
        (reference_audit, {"outcome": "accepted", "requested": None}, "requested"),
        (reference_audit, {"outcome": "accepted", "applied": None}, "applied"),
        (reference_audit, {"outcome": "dropped", "reason": None}, "reason"),
        (shot_card, {"duration_seconds": 0}, "duration_seconds"),
        (cue, {"start_seconds": -1}, "start_seconds"),
        (cue, {"start_seconds": 4, "end_seconds": 3}, "end_seconds"),
        (review_decision, {"score": 1.1}, "score"),
        (review_decision, {"confidence": -0.1}, "confidence"),
    ],
)
def test_core_value_constraints_are_rejected(factory: object, overrides: dict[str, object], field: str) -> None:
    with pytest.raises(VideoGenError, match=field):
        factory(**overrides)  # type: ignore[operator]


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("fact_sources", (FactSource("fact-1", "claim", "brief", True),) * 2),
        ("reference_audits", (reference_audit(),) * 2),
        ("shot_cards", (shot_card(),) * 2),
        ("cues", (cue(),) * 2),
        ("review_decisions", (review_decision(),) * 2),
    ],
)
def test_contract_rejects_duplicate_ids(field: str, replacement: tuple[object, ...]) -> None:
    with pytest.raises(VideoGenError, match=field):
        valid_contract(**{field: replacement})


def test_contract_rejects_cue_for_unknown_shot() -> None:
    with pytest.raises(VideoGenError, match=r"cue.*shot_id.*shot-missing"):
        valid_contract(cues=(cue(shot_id="shot-missing"),))
