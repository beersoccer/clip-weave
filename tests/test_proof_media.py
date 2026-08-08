from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

import pytest

from clip_weave.adapters.video_gen import VideoGenError
from clip_weave.core import proof_media
from clip_weave.core.proof_media import HttpPutProofMediaStore, ProofMediaStore, materialize_local_reference


class _Response:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def raise_for_status(self) -> None:
        if self.error:
            raise self.error


def _environment(**overrides: str) -> dict[str, str]:
    environment = {
        "PROOF_MEDIA_HTTPS_UPLOAD_URL_TEMPLATE": "https://upload.example/media/{sha256}{suffix}",
        "PROOF_MEDIA_HTTPS_URI_TEMPLATE": "https://cdn.example/media/{sha256}{suffix}",
    }
    environment.update(overrides)
    return environment


def test_proof_media_store_protocol_declares_uri_for_contract() -> None:
    parameters = inspect.signature(ProofMediaStore.uri_for).parameters

    assert tuple(parameters) == ("self", "scheme", "sha256", "suffix")
    assert all(parameters[name].kind is inspect.Parameter.KEYWORD_ONLY for name in ("scheme", "sha256", "suffix"))


def test_uploads_once_then_reuses_matching_ledger_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "reference.png"
    source.write_bytes(b"proof-media")
    ledger = tmp_path / "proof-media.json"
    calls: list[dict[str, object]] = []

    def fake_put(url: str, *, data: object, headers: dict[str, str]) -> _Response:
        calls.append({"url": url, "data": data.read(), "headers": headers})  # type: ignore[union-attr]
        return _Response()

    monkeypatch.setattr(proof_media.requests, "put", fake_put)
    store = HttpPutProofMediaStore.from_environment(_environment())

    created = materialize_local_reference(source, ledger, store, "https")
    reused = materialize_local_reference(source, ledger, store, "https")

    digest = hashlib.sha256(b"proof-media").hexdigest()
    assert created == proof_media.MaterializedReference(
        source=str(source),
        sha256=digest,
        suffix=".png",
        uri=f"https://cdn.example/media/{digest}.png",
        scheme="https",
        created=True,
    )
    assert reused.created is False
    assert len(calls) == 1
    assert calls[0]["headers"] == {"Content-Type": "image/png"}
    assert json.loads(ledger.read_text())["records"][0]["sha256"] == digest


def test_ledger_write_failure_deletes_newly_uploaded_object(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "reference.txt"
    source.write_text("proof")
    deleted: list[str] = []
    monkeypatch.setattr(proof_media.requests, "put", lambda *args, **kwargs: _Response())
    monkeypatch.setattr(proof_media.requests, "delete", lambda url: deleted.append(url) or _Response())
    monkeypatch.setattr(proof_media, "_write_ledger_atomically", lambda *args: (_ for _ in ()).throw(OSError("disk full")))
    store = HttpPutProofMediaStore.from_environment(_environment())

    with pytest.raises(VideoGenError, match="ledger.*disk full"):
        materialize_local_reference(source, tmp_path / "ledger.json", store, "https")

    assert deleted == [f"https://upload.example/media/{hashlib.sha256(b'proof').hexdigest()}.txt"]


def test_delete_failure_does_not_hide_ledger_write_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "reference.txt"
    source.write_text("proof")
    monkeypatch.setattr(proof_media.requests, "put", lambda *args, **kwargs: _Response())
    monkeypatch.setattr(proof_media.requests, "delete", lambda url: _Response(OSError("delete denied")))
    monkeypatch.setattr(proof_media, "_write_ledger_atomically", lambda *args: (_ for _ in ()).throw(OSError("disk full")))
    store = HttpPutProofMediaStore.from_environment(_environment())

    with pytest.raises(VideoGenError) as exc:
        materialize_local_reference(source, tmp_path / "ledger.json", store, "https")

    assert "disk full" in str(exc.value)
    assert "delete denied" in str(exc.value)


def test_ledger_write_failure_does_not_delete_reference_not_created_by_this_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "reference.txt"
    source.write_text("proof")
    deleted: list[MaterializedReference] = []
    digest = hashlib.sha256(b"proof").hexdigest()

    class ExistingObjectStore:
        def uri_for(self, *, scheme: str, sha256: str, suffix: str) -> str:
            return f"https://cdn.example/{sha256}{suffix}"

        def materialize(self, path: Path, *, scheme: str, sha256: str) -> proof_media.MaterializedReference:
            return proof_media.MaterializedReference(str(path), sha256, path.suffix, self.uri_for(scheme=scheme, sha256=sha256, suffix=path.suffix), scheme, False)

        def delete(self, reference: proof_media.MaterializedReference) -> None:
            deleted.append(reference)

    monkeypatch.setattr(proof_media, "_write_ledger_atomically", lambda *args: (_ for _ in ()).throw(OSError("disk full")))

    with pytest.raises(VideoGenError, match="disk full"):
        materialize_local_reference(source, tmp_path / "ledger.json", ExistingObjectStore(), "https")

    assert digest
    assert deleted == []


def test_directory_fsync_failure_after_replace_does_not_delete_recorded_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "reference.txt"
    source.write_text("proof")
    deleted: list[str] = []
    fsync_calls = 0

    def fake_fsync(fd: int) -> None:
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls == 2:
            raise OSError("directory fsync failed")

    monkeypatch.setattr(proof_media.requests, "put", lambda *args, **kwargs: _Response())
    monkeypatch.setattr(proof_media.requests, "delete", lambda url: deleted.append(url) or _Response())
    monkeypatch.setattr(proof_media.os, "fsync", fake_fsync)
    ledger = tmp_path / "ledger.json"
    store = HttpPutProofMediaStore.from_environment(_environment())

    with pytest.raises(VideoGenError, match="directory fsync failed"):
        materialize_local_reference(source, ledger, store, "https")

    assert json.loads(ledger.read_text())["records"]
    assert deleted == []


def test_rejects_missing_local_path(tmp_path: Path) -> None:
    store = HttpPutProofMediaStore.from_environment(_environment())

    with pytest.raises(VideoGenError, match="regular file"):
        materialize_local_reference(tmp_path / "missing.png", tmp_path / "ledger.json", store, "https")


@pytest.mark.parametrize(
    ("environment", "message"),
    [
        ({}, "UPLOAD_URL_TEMPLATE"),
        (
            {
                "PROOF_MEDIA_HTTPS_UPLOAD_URL_TEMPLATE": "https://upload.example/{sha256}",
                "PROOF_MEDIA_HTTPS_URI_TEMPLATE": "https://cdn.example/{sha256}{suffix}",
            },
            "suffix",
        ),
        (
            {
                "PROOF_MEDIA_HTTPS_UPLOAD_URL_TEMPLATE": "https://upload.example/{sha256}{suffix}",
                "PROOF_MEDIA_HTTPS_URI_TEMPLATE": "https://cdn.example/{sha256}{suffix}",
                "PROOF_MEDIA_HTTPS_UPLOAD_HEADERS_JSON": '{"Authorization": 2}',
            },
            "headers",
        ),
    ],
)
def test_rejects_missing_or_invalid_environment_templates(environment: dict[str, str], message: str) -> None:
    with pytest.raises(VideoGenError, match=message):
        HttpPutProofMediaStore.from_environment(environment)


def test_materializes_gs_uri(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "reference.bin"
    source.write_bytes(b"proof")
    environment = {
        "PROOF_MEDIA_GS_UPLOAD_URL_TEMPLATE": "https://upload.example/{sha256}{suffix}",
        "PROOF_MEDIA_GS_URI_TEMPLATE": "gs://proof-bucket/{sha256}{suffix}",
    }
    monkeypatch.setattr(proof_media.requests, "put", lambda *args, **kwargs: _Response())
    store = HttpPutProofMediaStore.from_environment(environment)

    reference = store.materialize(source, scheme="gs", sha256=hashlib.sha256(b"proof").hexdigest())

    assert reference.uri == f"gs://proof-bucket/{hashlib.sha256(b'proof').hexdigest()}.bin"


def test_configuration_error_does_not_leak_upload_headers() -> None:
    secret = "Bearer top-secret-value"
    environment = _environment(
        PROOF_MEDIA_HTTPS_URI_TEMPLATE="gs://bucket/{sha256}{suffix}",
        PROOF_MEDIA_HTTPS_UPLOAD_HEADERS_JSON=json.dumps({"Authorization": secret}),
    )

    with pytest.raises(VideoGenError) as exc:
        HttpPutProofMediaStore.from_environment(environment)

    assert secret not in str(exc.value)


def test_source_metadata_is_returned_for_new_reference(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "reference.txt"
    source.write_text("proof")
    monkeypatch.setattr(proof_media.requests, "put", lambda *args, **kwargs: _Response())
    store = HttpPutProofMediaStore.from_environment(_environment())

    reference = materialize_local_reference(
        source,
        tmp_path / "ledger.json",
        store,
        "https",
        source="https://example.test/original.txt",
    )

    assert reference.source == "https://example.test/original.txt"


def test_rejects_uri_template_with_wrong_scheme() -> None:
    environment = _environment(PROOF_MEDIA_HTTPS_URI_TEMPLATE="gs://bucket/{sha256}{suffix}")

    with pytest.raises(VideoGenError, match="URIs"):
        HttpPutProofMediaStore.from_environment(environment)
