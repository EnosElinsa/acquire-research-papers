from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping, Sequence
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit, urlunsplit


class InvalidPdfError(ValueError):
    """Downloaded bytes are not a complete PDF artifact."""


_SENSITIVE_ARTIFACT_KEYS = {
    "accesskey",
    "accesskeyid",
    "accesstoken",
    "apikey",
    "authorization",
    "authtoken",
    "bearertoken",
    "clientsecret",
    "clienttoken",
    "credential",
    "ossaccesskeyid",
    "password",
    "passwd",
    "securitytoken",
    "secret",
    "secretkey",
    "sessiontoken",
    "sig",
    "signature",
    "token",
    "xapikey",
    "xelsapikey",
    "xamzcredential",
    "xamzsecuritytoken",
    "xamzsignature",
    "xgoogcredential",
    "xgoogsignature",
    "xosssignature",
}


def _normalized_key(value: object) -> str:
    return "".join(character for character in str(value).casefold() if character.isalnum())


def _sanitize_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return value
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or not parsed.query:
        return value
    query_keys = {_normalized_key(key) for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
    if query_keys & _SENSITIVE_ARTIFACT_KEYS:
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    return value


def sanitize_artifact_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): sanitize_artifact_value(item)
            for key, item in value.items()
            if _normalized_key(key) not in _SENSITIVE_ARTIFACT_KEYS
        }
    if isinstance(value, tuple):
        return tuple(sanitize_artifact_value(item) for item in value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [sanitize_artifact_value(item) for item in value]
    if isinstance(value, str):
        return _sanitize_url(value)
    return value


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def validate_pdf(path: Path) -> None:
    size = path.stat().st_size
    with path.open("rb") as handle:
        header = handle.read(1024)
        if not header.startswith(b"%PDF-"):
            raise InvalidPdfError("PDF header is missing")
        handle.seek(max(0, size - 4096))
        trailer = handle.read()
    if b"%%EOF" not in trailer:
        raise InvalidPdfError("PDF EOF marker is missing")
    if size < 20:
        raise InvalidPdfError("PDF is too small to be complete")


def atomic_write_bytes(
    destination: Path,
    data: bytes,
    *,
    validator: Callable[[Path], None] | None = None,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(f"{destination.suffix}.partial")
    try:
        with partial.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if validator is not None:
            validator(partial)
        os.replace(partial, destination)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
