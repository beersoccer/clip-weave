"""Materialize local proof media into configured object storage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import mimetypes
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Mapping, Protocol
from urllib.parse import urlparse

import requests

from clip_weave.adapters.video_gen import VideoGenError


@dataclass(frozen=True)
class MaterializedReference:
    source: str
    sha256: str
    suffix: str
    uri: str
    scheme: str
    created: bool


class ProofMediaStore(Protocol):
    def uri_for(self, *, scheme: str, sha256: str, suffix: str) -> str: ...

    def materialize(self, path: Path, *, scheme: str, sha256: str) -> MaterializedReference: ...

    def delete(self, reference: MaterializedReference) -> None: ...


@dataclass(frozen=True)
class _SchemeConfig:
    upload_url_template: str
    uri_template: str
    headers: dict[str, str]


class _LedgerCommittedError(OSError):
    """The ledger was replaced, but its parent directory could not be synced."""


class HttpPutProofMediaStore:
    def __init__(self, configurations: Mapping[str, _SchemeConfig]) -> None:
        self._configurations = dict(configurations)

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> "HttpPutProofMediaStore":
        values = os.environ if environ is None else environ
        schemes = [
            scheme
            for scheme in ("https", "gs")
            if any(key.startswith(f"PROOF_MEDIA_{scheme.upper()}_") for key in values)
        ] or ["https"]
        configurations = {scheme: _configuration_from_environment(values, scheme) for scheme in schemes}
        return cls(configurations)

    def uri_for(self, *, scheme: str, sha256: str, suffix: str) -> str:
        config = self._configuration(scheme)
        uri = _expand_template(config.uri_template, sha256=sha256, suffix=suffix)
        if urlparse(uri).scheme != scheme:
            raise VideoGenError(f"proof media {scheme}: URI template produced wrong scheme")
        return uri

    def materialize(self, path: Path, *, scheme: str, sha256: str) -> MaterializedReference:
        config = self._configuration(scheme)
        suffix = path.suffix
        upload_url = _expand_template(config.upload_url_template, sha256=sha256, suffix=suffix)
        headers = dict(config.headers)
        headers["Content-Type"] = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        try:
            with path.open("rb") as media:
                response = requests.put(upload_url, data=media, headers=headers)
            response.raise_for_status()
        except requests.RequestException:
            request_error = VideoGenError(f"proof media {scheme}: upload request failed")
        else:
            return MaterializedReference(
                source=str(path),
                sha256=sha256,
                suffix=suffix,
                uri=self.uri_for(scheme=scheme, sha256=sha256, suffix=suffix),
                scheme=scheme,
                created=True,
            )
        raise request_error from None

    def delete(self, reference: MaterializedReference) -> None:
        config = self._configuration(reference.scheme)
        upload_url = _expand_template(
            config.upload_url_template,
            sha256=reference.sha256,
            suffix=reference.suffix,
        )
        try:
            response = requests.delete(upload_url, headers=dict(config.headers))
            response.raise_for_status()
        except requests.RequestException:
            request_error = VideoGenError(f"proof media {reference.scheme}: delete request failed")
        else:
            return
        raise request_error from None

    def _configuration(self, scheme: str) -> _SchemeConfig:
        try:
            return self._configurations[scheme]
        except KeyError as exc:
            raise VideoGenError(f"proof media: unsupported scheme {scheme!r}") from exc


def materialize_local_reference(
    path: Path,
    ledger_path: Path,
    store: ProofMediaStore,
    scheme: str,
    *,
    source: str | None = None,
    source_note: str | None = None,
    license_note: str | None = None,
) -> MaterializedReference:
    if not path.is_file():
        raise VideoGenError(f"proof media path must be a regular file: {path}")

    sha256 = _sha256_file(path)
    suffix = path.suffix
    uri = _uri_for(store, scheme=scheme, sha256=sha256, suffix=suffix)
    ledger = _read_ledger(ledger_path)
    for record in ledger["records"]:
        if _is_matching_record(record, sha256=sha256, suffix=suffix, scheme=scheme, uri=uri):
            return MaterializedReference(
                source=str(source if source is not None else path),
                sha256=sha256,
                suffix=suffix,
                uri=uri,
                scheme=scheme,
                created=False,
            )

    created = store.materialize(path, scheme=scheme, sha256=sha256)
    record = {
        "source": source if source is not None else str(path),
        "sha256": sha256,
        "suffix": suffix,
        "uri": created.uri,
        "scheme": scheme,
        "source_note": source_note,
        "license_note": license_note,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    ledger["records"].append(record)
    try:
        _write_ledger_atomically(ledger_path, ledger)
    except _LedgerCommittedError as ledger_error:
        raise VideoGenError(f"proof media ledger write failed after replacement: {ledger_error}") from ledger_error
    except Exception as ledger_error:
        if not created.created:
            raise VideoGenError(f"proof media ledger write failed: {ledger_error}") from ledger_error
        try:
            store.delete(created)
        except Exception as delete_error:
            raise VideoGenError(
                f"proof media ledger write failed: {ledger_error}; object deletion failed: {delete_error}"
            ) from ledger_error
        raise VideoGenError(f"proof media ledger write failed: {ledger_error}") from ledger_error
    if source is None:
        return created
    return MaterializedReference(
        source=source,
        sha256=created.sha256,
        suffix=created.suffix,
        uri=created.uri,
        scheme=created.scheme,
        created=created.created,
    )


def _configuration_from_environment(values: Mapping[str, str], scheme: str) -> _SchemeConfig:
    prefix = f"PROOF_MEDIA_{scheme.upper()}_"
    upload_template = values.get(prefix + "UPLOAD_URL_TEMPLATE")
    uri_template = values.get(prefix + "URI_TEMPLATE")
    if not upload_template or not uri_template:
        raise VideoGenError(f"proof media {scheme}: UPLOAD_URL_TEMPLATE and URI_TEMPLATE are required")
    for name, template in (("UPLOAD_URL_TEMPLATE", upload_template), ("URI_TEMPLATE", uri_template)):
        if "{sha256}" not in template or "{suffix}" not in template:
            raise VideoGenError(f"proof media {scheme}: {name} must contain {{sha256}} and {{suffix}}")
    headers_value = values.get(prefix + "UPLOAD_HEADERS_JSON")
    headers: dict[str, str] = {}
    if headers_value is not None:
        try:
            decoded = json.loads(headers_value)
        except json.JSONDecodeError as exc:
            raise VideoGenError(f"proof media {scheme}: upload headers must be a string:string object") from exc
        if not isinstance(decoded, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in decoded.items()):
            raise VideoGenError(f"proof media {scheme}: upload headers must be a string:string object")
        headers = decoded
    rendered_uri = _expand_template(uri_template, sha256="a", suffix=".x")
    if urlparse(rendered_uri).scheme != scheme:
        raise VideoGenError(f"proof media {scheme}: URI template must produce {scheme} URIs")
    return _SchemeConfig(upload_template, uri_template, headers)


def _expand_template(template: str, *, sha256: str, suffix: str) -> str:
    try:
        return template.format(sha256=sha256, suffix=suffix)
    except (KeyError, ValueError) as exc:
        raise VideoGenError("proof media template is invalid") from exc


def _uri_for(store: ProofMediaStore, *, scheme: str, sha256: str, suffix: str) -> str:
    uri_for = getattr(store, "uri_for", None)
    if uri_for is None:
        raise VideoGenError("proof media store must expose uri_for for ledger reuse")
    return uri_for(scheme=scheme, sha256=sha256, suffix=suffix)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as media:
        for chunk in iter(lambda: media.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_ledger(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"schema_version": 1, "records": []}
    try:
        ledger = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VideoGenError(f"invalid proof media ledger {path}: {exc}") from exc
    if not isinstance(ledger, dict) or ledger.get("schema_version") != 1 or not isinstance(ledger.get("records"), list):
        raise VideoGenError(f"invalid proof media ledger {path}")
    return ledger


def _is_matching_record(record: object, *, sha256: str, suffix: str, scheme: str, uri: str) -> bool:
    return isinstance(record, dict) and all(
        record.get(key) == value
        for key, value in (("sha256", sha256), ("suffix", suffix), ("scheme", scheme), ("uri", uri))
    )


def _write_ledger_atomically(path: Path, ledger: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    replaced = False
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(ledger, temporary, sort_keys=True)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
        replaced = True
        temporary_path = None
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception as exc:
        if replaced:
            raise _LedgerCommittedError(str(exc)) from exc
        raise
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
