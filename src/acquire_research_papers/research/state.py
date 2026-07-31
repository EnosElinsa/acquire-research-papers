from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from acquire_research_papers.artifacts import atomic_write_bytes, sha256_bytes, sha256_file
from acquire_research_papers.discovery.contracts import CandidateMetadata
from acquire_research_papers.discovery.coordinator import candidate_identity
from acquire_research_papers.schema_resources import schema


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def validate_record(value: Mapping[str, Any], schema_name: str) -> None:
    contract = schema(schema_name)
    errors = sorted(
        Draft202012Validator(contract).iter_errors(dict(value)),
        key=lambda item: list(item.path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path)
        raise ValueError(f"{location or '$'}: {error.message}")


def research_candidate_id(candidate: CandidateMetadata) -> str:
    return sha256_bytes(candidate_identity(candidate).encode("utf-8"))[:24]


def candidate_packet(candidate: CandidateMetadata) -> dict[str, Any]:
    payload = candidate.to_dict()
    return {
        "schema_version": 1,
        "candidate_id": research_candidate_id(candidate),
        "candidate_sha256": sha256_bytes(canonical_json(payload)),
        "candidate": payload,
    }


def encode_packets(candidates: list[CandidateMetadata]) -> bytes:
    return b"".join(
        canonical_json(candidate_packet(candidate)) + b"\n" for candidate in candidates
    )


def load_candidate_packets(path: Path) -> tuple[dict[str, Any], ...]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ValueError("research candidate snapshot could not be read") from exc
    packets: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        for line in lines:
            if not line.strip():
                continue
            packet = json.loads(line)
            if not isinstance(packet, dict) or packet.get("schema_version") != 1:
                raise ValueError("research candidate packet has an unsupported schema")
            payload = packet.get("candidate")
            if not isinstance(payload, dict):
                raise ValueError("research candidate packet has no candidate")
            candidate = CandidateMetadata.from_dict(payload)
            expected_id = research_candidate_id(candidate)
            expected_hash = sha256_bytes(canonical_json(payload))
            if packet.get("candidate_id") != expected_id:
                raise ValueError("research candidate ID mismatch")
            if packet.get("candidate_sha256") != expected_hash:
                raise ValueError("research candidate SHA-256 mismatch")
            if expected_id in seen:
                raise ValueError("research candidate snapshot contains a duplicate candidate")
            seen.add(expected_id)
            packets.append(packet)
    except json.JSONDecodeError as exc:
        raise ValueError("research candidate snapshot is not valid JSON Lines") from exc
    return tuple(packets)


def read_run_manifest(root: Path) -> dict[str, Any]:
    resolved_root = root.resolve()
    path = resolved_root / "research-run.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("research run manifest could not be read") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError("research run manifest has an unsupported schema")
    snapshot = resolved_root / str(manifest.get("candidates_file") or "")
    if snapshot.parent != resolved_root or not snapshot.is_file():
        raise ValueError("research candidate snapshot path is invalid")
    if sha256_file(snapshot) != manifest.get("candidates_sha256"):
        raise ValueError("research candidate snapshot SHA-256 mismatch")
    brief = manifest.get("brief")
    if not isinstance(brief, dict) or sha256_bytes(canonical_json(brief)) != manifest.get(
        "brief_sha256"
    ):
        raise ValueError("research brief SHA-256 mismatch")
    return manifest


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    atomic_write_bytes(
        path,
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        + b"\n",
    )


def validate_review_audit(root: Path, selection_manifest: Mapping[str, Any]) -> Path:
    destination = root.resolve()
    reviewed_path = (
        destination / str(selection_manifest.get("reviewed_file") or "")
    ).resolve()
    if (
        reviewed_path.parent != destination
        or not reviewed_path.is_file()
        or sha256_file(reviewed_path) != selection_manifest.get("reviewed_sha256")
    ):
        raise ValueError("research review audit SHA-256 mismatch")
    manifest_path = (
        destination / str(selection_manifest.get("review_manifest_file") or "")
    ).resolve()
    if (
        manifest_path.parent != destination
        or not manifest_path.is_file()
        or sha256_file(manifest_path)
        != selection_manifest.get("review_manifest_sha256")
    ):
        raise ValueError("research review manifest SHA-256 mismatch")
    return reviewed_path


def update_run_manifest(root: Path, **changes: Any) -> dict[str, Any]:
    manifest = read_run_manifest(root)
    manifest.update(changes)
    write_json(root.resolve() / "research-run.json", manifest)
    return manifest


def claim_ids(brief: Mapping[str, Any]) -> tuple[str, ...]:
    values: list[str] = []
    for index, claim in enumerate(brief.get("claims") or (), start=1):
        if isinstance(claim, str):
            value = claim.strip()
            values.append(f"claim-{index}" if value else "")
        elif isinstance(claim, Mapping):
            values.append(str(claim.get("id") or "").strip())
    filtered = tuple(value for value in values if value)
    return filtered or ("research-question",)
