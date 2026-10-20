from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def review_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate review provenance without upgrading or rewriting legacy records.

    Unversioned and v1 reviews retain the historical Codex identity. New v2
    reviews name the executing host in both reviewer and executor.host. Host
    names remain extensible; this validates the attribution, not host access.
    """
    version = payload.get("schema_version", 1)
    if type(version) is not int or version not in {1, 2}:
        raise ValueError("review schema_version must be 1 or 2")
    reviewer = payload.get("reviewer")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError("reviewer must be a nonempty host name")
    metadata: dict[str, Any] = {"reviewer": reviewer}
    if "schema_version" in payload:
        metadata["schema_version"] = version
    if version == 1:
        if reviewer != "codex":
            raise ValueError("legacy reviewer must be codex; other hosts require schema_version=2")
        if "executor" in payload:
            raise ValueError("review executor metadata requires schema_version=2")
        return metadata

    executor = payload.get("executor")
    if not isinstance(executor, dict):
        raise ValueError("v2 review executor metadata is required")
    if set(executor) - {"host", "model", "version"}:
        raise ValueError("review executor contains unknown fields")
    host = executor.get("host")
    if not isinstance(host, str) or not host.strip():
        raise ValueError("review executor.host must be a nonempty host name")
    if host != reviewer:
        raise ValueError("review executor.host must match reviewer")
    for field in ("model", "version"):
        if field in executor and (
            not isinstance(executor[field], str) or not executor[field].strip()
        ):
            raise ValueError(f"review executor.{field} must be a nonempty string")
    metadata["executor"] = dict(executor)
    return metadata
