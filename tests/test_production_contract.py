from __future__ import annotations

from dataclasses import fields
from dataclasses import FrozenInstanceError
from fractions import Fraction
import json
from math import inf, nan
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from clip_weave.adapters.video_gen import VideoGenError
from clip_weave.core.production_contract import (
    CreativeContract,
    ContractRevision,
    Cue,
    FactSource,
    ProductionContract,
    ReferenceAudit,
    ReviewDecision,
    ShotCard,
    append_contract_revision,
    load_contract_revision,
    load_current_contract,
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
        "target_revision": 1,
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
        "facts_sources": (
            FactSource(
                id="fact-1",
                claim="The product supports shared review.",
                source="approved product brief",
                approved=True,
            ),
        ),
        "reference_audits": (reference_audit(),),
        "shot_cards": (shot_card(),),
        "cue_sheet": (cue(),),
        "review_decisions": (review_decision(),),
    }
    values.update(overrides)
    return ProductionContract(**values)  # type: ignore[arg-type]


def test_valid_complete_snapshot_is_frozen() -> None:
    contract = valid_contract()

    assert contract.shot_cards[0].reference_audit_refs == ("audit-1",)
    assert contract.cue_sheet[0].shot_id == "shot-1"
    with pytest.raises(FrozenInstanceError):
        contract.creative_contract.audience = "another audience"  # type: ignore[misc]


def test_contract_exposes_approved_top_level_field_names() -> None:
    assert [field.name for field in fields(ProductionContract)] == [
        "creative_contract",
        "facts_sources",
        "reference_audits",
        "shot_cards",
        "cue_sheet",
        "review_decisions",
    ]


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
        (creative_contract, {"production_profile": []}, "production_profile"),
        (reference_audit, {"subject_type": []}, "subject_type"),
        (reference_audit, {"requirement": []}, "requirement"),
        (reference_audit, {"outcome": []}, "outcome"),
        (cue, {"kind": []}, "kind"),
        (review_decision, {"decision": []}, "decision"),
    ],
)
def test_non_string_enum_values_raise_video_gen_error(
    factory: object,
    overrides: dict[str, object],
    field: str,
) -> None:
    with pytest.raises(VideoGenError, match=field):
        factory(**overrides)  # type: ignore[operator]


def test_unhashable_string_enum_value_raises_video_gen_error() -> None:
    class UnhashableString(str):
        __hash__ = None  # type: ignore[assignment]

    with pytest.raises(VideoGenError, match="production_profile"):
        creative_contract(production_profile=UnhashableString("html_launch"))


@pytest.mark.parametrize(
    ("factory", "overrides", "field"),
    [
        (creative_contract, {"audience": ""}, "audience"),
        (creative_contract, {"must_keep": ("",)}, "must_keep"),
        (FactSource, {"id": "fact-1", "claim": "claim", "source": "brief", "approved": 1}, "approved"),
        (reference_audit, {"outcome": "accepted", "requested": None}, "requested"),
        (reference_audit, {"outcome": "accepted", "applied": None}, "applied"),
        (reference_audit, {"outcome": "dropped", "reason": None}, "reason"),
        (reference_audit, {"outcome": "blocked", "reason": None}, "reason"),
        (creative_contract, {"target_duration_seconds": 1.5}, "target_duration_seconds"),
        (creative_contract, {"target_duration_seconds": True}, "target_duration_seconds"),
        (creative_contract, {"target_duration_seconds": 0}, "target_duration_seconds"),
        (creative_contract, {"target_duration_seconds": -1}, "target_duration_seconds"),
        (creative_contract, {"target_duration_seconds": nan}, "target_duration_seconds"),
        (creative_contract, {"target_duration_seconds": inf}, "target_duration_seconds"),
        (shot_card, {"duration_seconds": 0}, "duration_seconds"),
        (cue, {"start_seconds": -1}, "start_seconds"),
        (cue, {"start_seconds": 4, "end_seconds": 3}, "end_seconds"),
        (cue, {"start_seconds": nan}, "start_seconds"),
        (cue, {"end_seconds": inf}, "end_seconds"),
        (review_decision, {"score": 1.1}, "score"),
        (review_decision, {"confidence": -0.1}, "confidence"),
    ],
)
def test_core_value_constraints_are_rejected(factory: object, overrides: dict[str, object], field: str) -> None:
    with pytest.raises(VideoGenError, match=field):
        factory(**overrides)  # type: ignore[operator]


@pytest.mark.parametrize(
    "target_revision",
    [0, -1, True, 1.5, nan, inf, "1"],
)
def test_review_decision_requires_positive_integer_revision(target_revision: object) -> None:
    with pytest.raises(VideoGenError, match="target_revision"):
        review_decision(target_revision=target_revision)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("facts_sources", (FactSource("fact-1", "claim", "brief", True),) * 2),
        ("reference_audits", (reference_audit(),) * 2),
        ("shot_cards", (shot_card(),) * 2),
        ("cue_sheet", (cue(),) * 2),
    ],
)
def test_contract_rejects_duplicate_ids(field: str, replacement: tuple[object, ...]) -> None:
    with pytest.raises(VideoGenError, match=field):
        valid_contract(**{field: replacement})


def test_contract_rejects_cue_for_unknown_shot() -> None:
    with pytest.raises(VideoGenError, match=r"cue.*shot_id.*shot-missing"):
        valid_contract(cue_sheet=(cue(shot_id="shot-missing"),))


def test_contract_allows_multiple_decisions_for_target_at_different_revisions() -> None:
    contract = valid_contract(
        review_decisions=(review_decision(), review_decision(target_revision=2, decision="revise")),
    )

    assert [decision.target_revision for decision in contract.review_decisions] == [1, 2]


def test_contract_rejects_duplicate_unhashable_fact_id_without_type_error() -> None:
    class UnhashableString(str):
        __hash__ = None  # type: ignore[assignment]

    fact_id = UnhashableString("fact-1")
    facts = (
        FactSource(fact_id, "first claim", "brief", True),
        FactSource(fact_id, "second claim", "brief", True),
    )

    with pytest.raises(VideoGenError, match="facts_sources"):
        valid_contract(facts_sources=facts)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("creative_contract", object()),
        ("facts_sources", (object(),)),
        ("reference_audits", (object(),)),
        ("shot_cards", (object(),)),
        ("cue_sheet", (object(),)),
        ("review_decisions", (object(),)),
    ],
)
def test_contract_rejects_wrong_child_object_type(field: str, replacement: object) -> None:
    with pytest.raises(VideoGenError, match=field):
        valid_contract(**{field: replacement})


def ledger_path(project_dir: Path) -> Path:
    return project_dir / "renders" / "production-contract.json"


def write_ledger(project_dir: Path, payload: object) -> None:
    path = ledger_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_append_first_contract_revision_creates_versioned_ledger(tmp_path: Path) -> None:
    contract = valid_contract()

    record = append_contract_revision(tmp_path, contract, reason="Initial creative approval")

    assert record == ContractRevision(1, record.created_at, "Initial creative approval", contract)
    payload = json.loads(ledger_path(tmp_path).read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["current_revision"] == 1
    assert payload["revisions"] == [{
        "revision": 1,
        "created_at": record.created_at,
        "reason": "Initial creative approval",
        "contract": {
            "creative_contract": {
                "production_profile": "html_launch",
                "audience": "product leaders",
                "platform": "web",
                "target_duration_seconds": 30,
                "narrative_promise": "Show the product value clearly.",
                "must_keep": ["brand blue"],
                "must_not": ["unsupported claims"],
            },
            "facts_sources": [{"id": "fact-1", "claim": "The product supports shared review.", "source": "approved product brief", "approved": True}],
            "reference_audits": [{"audit_id": "audit-1", "shot_id": "shot-1", "subject_type": "product", "requirement": "required", "requested": "product.png", "submitted": "gs://proof/product.png", "applied": "gs://proof/product.png", "outcome": "accepted", "reason": None, "proof_media_ref": "proof-1"}],
            "shot_cards": [{"shot_id": "shot-1", "purpose": "Introduce the product.", "subject": "The product interface", "action": "opens to the dashboard", "scene": "dark studio", "camera": "slow dolly in", "lighting": "soft blue rim light", "duration_seconds": 5, "must_keep": ["logo"], "must_not": ["text glitches"], "reference_audit_refs": ["audit-1"]}],
            "cue_sheet": [{"cue_id": "cue-1", "start_seconds": 0, "end_seconds": 3, "kind": "vo", "content": "A clearer way to launch.", "shot_id": "shot-1"}],
            "review_decisions": [{"target_type": "shot", "target_id": "shot-1", "target_revision": 1, "decision": "accepted", "reasons": ["Matches the creative contract."], "score": 0.9, "confidence": 0.8, "reviewer": "director", "reviewed_at": "2026-08-09T10:00:00+08:00"}],
        },
    }]


def test_append_second_contract_revision_preserves_first_snapshot_and_loads_current(tmp_path: Path) -> None:
    first = valid_contract()
    second = valid_contract(creative_contract=creative_contract(audience="creative directors"))
    append_contract_revision(tmp_path, first, reason="Initial approval")

    record = append_contract_revision(tmp_path, second, reason="Audience refinement")

    assert record.revision == 2
    assert load_contract_revision(tmp_path, 1) == first
    assert load_contract_revision(tmp_path, 2) == second
    assert load_current_contract(tmp_path) == second


def test_load_current_contract_returns_none_when_ledger_does_not_exist(tmp_path: Path) -> None:
    assert load_current_contract(tmp_path) is None


def test_load_contract_revision_rejects_missing_revision(tmp_path: Path) -> None:
    append_contract_revision(tmp_path, valid_contract(), reason="Initial approval")

    with pytest.raises(VideoGenError, match=r"production-contract\.json.*revision 2"):
        load_contract_revision(tmp_path, 2)


@pytest.mark.parametrize("revision", [True, 1.0, 0, -1])
def test_load_contract_revision_requires_positive_builtin_integer(tmp_path: Path, revision: object) -> None:
    append_contract_revision(tmp_path, valid_contract(), reason="Initial approval")

    with pytest.raises(VideoGenError, match="revision"):
        load_contract_revision(tmp_path, revision)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda payload: payload["revisions"][0].update(revision=2), "continuous"),
        (lambda payload: payload.update(current_revision=2), "current_revision"),
    ],
)
def test_load_rejects_noncontinuous_revision_or_wrong_current_pointer(
    tmp_path: Path,
    mutation: object,
    message: str,
) -> None:
    append_contract_revision(tmp_path, valid_contract(), reason="Initial approval")
    path = ledger_path(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutation(payload)  # type: ignore[operator]
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(VideoGenError, match=rf"production-contract\.json.*{message}"):
        load_current_contract(tmp_path)


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": 2, "current_revision": 1, "revisions": []},
        {"schema_version": True, "current_revision": 1, "revisions": []},
        {"schema_version": 1, "current_revision": 2, "revisions": []},
        {"schema_version": 1, "current_revision": 1, "revisions": [{"revision": 2}]},
        {"schema_version": 1, "current_revision": 1, "revisions": [], "unknown": True},
    ],
)
def test_load_rejects_invalid_ledger_shape(tmp_path: Path, payload: object) -> None:
    write_ledger(tmp_path, payload)

    with pytest.raises(VideoGenError, match=r"production-contract\.json"):
        load_current_contract(tmp_path)


def test_load_rejects_malformed_json_without_overwriting_ledger(tmp_path: Path) -> None:
    path = ledger_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{invalid", encoding="utf-8")

    with pytest.raises(VideoGenError, match=r"production-contract\.json"):
        load_current_contract(tmp_path)

    assert path.read_text(encoding="utf-8") == "{invalid"


def test_append_rejects_blank_reason_without_creating_ledger(tmp_path: Path) -> None:
    with pytest.raises(VideoGenError, match="reason"):
        append_contract_revision(tmp_path, valid_contract(), reason="  ")

    assert not ledger_path(tmp_path).exists()


@pytest.mark.parametrize(
    ("factory", "overrides", "field"),
    [
        (shot_card, {"duration_seconds": Fraction(1, 2)}, "duration_seconds"),
        (cue, {"start_seconds": Fraction(1, 2)}, "start_seconds"),
        (review_decision, {"score": Fraction(1, 2)}, "score"),
        (review_decision, {"confidence": Fraction(1, 2)}, "confidence"),
    ],
)
def test_contract_rejects_non_json_fraction_numbers(
    factory: object,
    overrides: dict[str, object],
    field: str,
) -> None:
    with pytest.raises(VideoGenError, match=field):
        factory(**overrides)  # type: ignore[operator]


def test_append_rejects_damaged_ledger_without_overwriting_its_bytes(tmp_path: Path) -> None:
    path = ledger_path(tmp_path)
    path.parent.mkdir(parents=True)
    original = b'{"schema_version": 2}'
    path.write_bytes(original)

    with pytest.raises(VideoGenError, match=r"production-contract\.json"):
        append_contract_revision(tmp_path, valid_contract(), reason="Initial approval")

    assert path.read_bytes() == original


def test_append_replace_failure_preserves_existing_ledger_and_cleans_temporary_file(tmp_path: Path) -> None:
    first = valid_contract()
    append_contract_revision(tmp_path, first, reason="Initial approval")
    path = ledger_path(tmp_path)
    original = path.read_bytes()

    with patch.object(os, "replace", side_effect=OSError("replace failed")):
        with pytest.raises(OSError, match="replace failed") as error:
            append_contract_revision(tmp_path, valid_contract(), reason="Second approval")

    assert type(error.value) is OSError
    assert path.read_bytes() == original
    assert list(path.parent.glob(".production-contract-*.tmp")) == []


def test_append_preserves_replace_failure_when_temporary_cleanup_fails(tmp_path: Path) -> None:
    append_contract_revision(tmp_path, valid_contract(), reason="Initial approval")
    path = ledger_path(tmp_path)
    original = path.read_bytes()

    with patch.object(os, "replace", side_effect=OSError("replace failed")), patch.object(
        Path, "unlink", side_effect=OSError("cleanup failed")
    ) as unlink:
        with pytest.raises(OSError, match="replace failed") as error:
            append_contract_revision(tmp_path, valid_contract(), reason="Second approval")

    assert type(error.value) is OSError
    unlink.assert_called_once()
    assert path.read_bytes() == original


def test_append_wraps_temporary_cleanup_failure(tmp_path: Path) -> None:
    append_contract_revision(tmp_path, valid_contract(), reason="Initial approval")

    with patch.object(os.path, "exists", return_value=True), patch.object(
        Path, "unlink", side_effect=OSError("cleanup failed")
    ):
        with pytest.raises(VideoGenError, match=r"production-contract\.json.*cleanup failed") as error:
            append_contract_revision(tmp_path, valid_contract(), reason="Second approval")

    assert type(error.value) is VideoGenError
    assert isinstance(error.value.__cause__, OSError)
    assert str(error.value.__cause__) == "cleanup failed"


def test_append_reports_directory_sync_failure_after_replacement(tmp_path: Path) -> None:
    append_contract_revision(tmp_path, valid_contract(), reason="Initial approval")

    with patch.object(os, "fsync", side_effect=(None, OSError("directory sync failed"))):
        with pytest.raises(VideoGenError, match=r"production-contract\.json.*replacement completed.*directory sync failed") as error:
            append_contract_revision(tmp_path, valid_contract(), reason="Second approval")

    assert isinstance(error.value.__cause__, OSError)
    assert load_contract_revision(tmp_path, 2) == valid_contract()
