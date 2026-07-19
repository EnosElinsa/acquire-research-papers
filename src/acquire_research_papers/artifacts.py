from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from pathlib import Path


class InvalidPdfError(ValueError):
    """Downloaded bytes are not a complete PDF artifact."""


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
