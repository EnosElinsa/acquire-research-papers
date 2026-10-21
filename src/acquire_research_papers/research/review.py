from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from acquire_research_papers.artifacts import (
    atomic_write_bytes,
    sha256_bytes,
    sha256_file,
)
from acquire_research_papers.discovery.contracts import CandidateMetadata
from acquire_research_papers.research.state import (
    claim_ids,
    load_candidate_packets,
    read_run_manifest,
    update_run_manifest,
    validate_record,
)
from acquire_research_papers.review_contracts import review_metadata
from acquire_research_papers.selection import SelectionStore, build_selection_records


@dataclass(frozen=True)
class ResearchReviewResult:
    status: str
    manifest_path: Path
    reviewed_path: Path
    pending_path: Path | None
    selection_manifest_path: Path | None
    included: int
    excluded: int
    pending: int


def _load_decisions(path: Path) -> dict[str, dict[str, Any]]:
    decisions: dict[str, dict[str, Any]] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        for line in lines:
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("research decision must be an object")
            validate_record(value, "research-review-decision.schema.json")
            review_metadata(value)
            candidate_id = str(value.get("candidate_id") or "")
            if not candidate_id or candidate_id in decisions:
                raise ValueError("research decisions contain a missing or duplicate candidate_id")
            decisions[candidate_id] = value
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("research decisions could not be read as JSON Lines") from exc
    return decisions


def _write_pending(path: Path | None, rows: list[dict[str, Any]]) -> None:
    if path is None:
        return
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=["candidate_id", "title", "reason"])
    writer.writeheader()
    writer.writerows(rows)
    atomic_write_bytes(path, buffer.getvalue().encode("utf-8-sig"))


class ResearchReviewWorkflow:
    """Validate explicit semantic decisions and freeze the closest-paper set."""

    def run(self, root: Path, decisions_path: Path) -> ResearchReviewResult:
        destination = root.resolve()
        run = read_run_manifest(destination)
        snapshot = destination / str(run["candidates_file"])
        packets = load_candidate_packets(snapshot)
        reviewed_path = destination / "reviewed-research.jsonl"
        manifest_path = destination / "research-review.json"
        decisions: dict[str, dict[str, Any]] = {}
        if reviewed_path.is_file():
            try:
                prior_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError("research review manifest could not be read") from exc
            if not isinstance(prior_manifest, dict) or sha256_file(
                reviewed_path
            ) != prior_manifest.get("reviewed_sha256"):
                raise ValueError("research review audit SHA-256 mismatch")
            decisions = _load_decisions(reviewed_path)
        elif manifest_path.exists():
            raise ValueError("research review audit is missing")
        decisions.update(_load_decisions(decisions_path))
        packet_ids = {str(packet["candidate_id"]) for packet in packets}
        if set(decisions) - packet_ids:
            raise ValueError("research decisions reference an unknown candidate")
        valid_claims = set(claim_ids(run["brief"]))
        reviewed: list[dict[str, Any]] = []
        pending_rows: list[dict[str, Any]] = []
        included_candidates: list[CandidateMetadata] = []
        excluded = 0
        for packet in packets:
            candidate_id = str(packet["candidate_id"])
            candidate = CandidateMetadata.from_dict(packet["candidate"])
            decision = decisions.get(candidate_id)
            if decision is None:
                pending_rows.append(
                    {
                        "candidate_id": candidate_id,
                        "title": candidate.title,
                        "reason": "explicit agent relevance decision required",
                    }
                )
                continue
            if decision.get("candidate_sha256") != packet["candidate_sha256"]:
                raise ValueError("research decision candidate SHA-256 mismatch")
            verdict = str(decision.get("decision") or "")
            if verdict not in {"include", "exclude"}:
                raise ValueError("research decision must be include or exclude")
            reason = str(decision.get("reason") or "").strip()
            if not reason:
                raise ValueError("research decision reason is required")
            claims = tuple(str(value) for value in decision.get("claims") or ())
            if set(claims) - valid_claims:
                raise ValueError("research decision references an unknown claim")
            if verdict == "include":
                if not candidate.abstract.strip() or not {
                    "title",
                    "abstract",
                }.issubset(candidate.evidence_fields):
                    raise ValueError(
                        "research inclusion requires title and abstract evidence"
                    )
                included_candidates.append(candidate)
            else:
                excluded += 1
            reviewed.append(
                {
                    "candidate_id": candidate_id,
                    "candidate_sha256": packet["candidate_sha256"],
                    "decision": verdict,
                    "claims": list(claims),
                    "reason": reason,
                    **review_metadata(decision),
                }
            )
        maximum = int((run["brief"].get("analysis") or {}).get("max_full_text_papers", 20))
        if len(included_candidates) > maximum:
            raise ValueError("research review exceeds analysis.max_full_text_papers")
        reviewed_bytes = b"".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n"
            for row in reviewed
        )
        reviewed_sha256 = sha256_bytes(reviewed_bytes)

        pending_path = destination / "pending-research-review.csv"
        if not pending_rows and run.get("output_version", 1) >= 2:
            pending_path.unlink(missing_ok=True)
            pending_path = None
        selection_manifest: Path | None = None
        existing_selection_path = destination / "selection" / "selection-manifest.json"
        selection_relative: str | None
        if pending_rows:
            if existing_selection_path.is_file():
                raise ValueError("a frozen research selection cannot return to pending review")
            status = "review_required"
            selection_relative = None
        else:
            if not included_candidates:
                raise ValueError("research review must include at least one closest paper")
            status = "acquisition_required"
            selection_relative = "selection/selection-manifest.json"
        review_manifest_payload = {
            "schema_version": 1,
            "phase": "research-review",
            "status": status,
            "candidate_snapshot_sha256": run["candidates_sha256"],
            "reviewed": len(reviewed),
            "reviewed_sha256": reviewed_sha256,
            "included": len(included_candidates),
            "excluded": excluded,
            "pending": len(pending_rows),
            "reviewed_file": reviewed_path.name,
            "pending_file": pending_path.name if pending_path else None,
            "selection_manifest": selection_relative,
        }
        review_manifest_bytes = (
            json.dumps(
                review_manifest_payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ).encode("utf-8")
            + b"\n"
        )
        review_manifest_sha256 = sha256_bytes(review_manifest_bytes)
        if not pending_rows:
            records = build_selection_records(
                included_candidates,
                venues=(),
                delivery={"profile": "generic"},
            )
            if existing_selection_path.is_file():
                selection = SelectionStore.load(existing_selection_path)
                if (
                    selection.manifest.get("reviewed_file") != reviewed_path.name
                    or selection.manifest.get("reviewed_sha256") != reviewed_sha256
                    or selection.manifest.get("review_manifest_file")
                    != manifest_path.name
                    or selection.manifest.get("review_manifest_sha256")
                    != review_manifest_sha256
                    or not manifest_path.is_file()
                    or sha256_file(manifest_path) != review_manifest_sha256
                ):
                    raise ValueError("frozen research review differs from review decisions")
                if (
                    selection.records != records
                    or selection.manifest.get("spec") != run["brief"]
                    or selection.manifest.get("phase") != "research-review"
                    or selection.manifest.get("candidate_snapshot_sha256")
                    != run["candidates_sha256"]
                ):
                    raise ValueError("frozen research selection differs from review decisions")
            else:
                # Publish the audit first so an interrupted selection write can resume.
                atomic_write_bytes(reviewed_path, reviewed_bytes)
                _write_pending(pending_path, pending_rows)
                atomic_write_bytes(manifest_path, review_manifest_bytes)
                selection = SelectionStore.write(
                    destination / "selection",
                    run["brief"],
                    records,
                    discovery_summary={
                        "phase": "research-review",
                        "candidate_snapshot_sha256": run["candidates_sha256"],
                        "reviewed_count": len(reviewed),
                        "reviewed_file": reviewed_path.name,
                        "reviewed_sha256": reviewed_sha256,
                        "review_manifest_file": manifest_path.name,
                        "review_manifest_sha256": review_manifest_sha256,
                    },
                )
            selection_manifest = selection.manifest_path
        if existing_selection_path.is_file() and run.get("phase") in {
            "full-text",
            "evidence",
        }:
            if not manifest_path.is_file() or not reviewed_path.is_file():
                raise ValueError("frozen research review artifacts are incomplete")
            return ResearchReviewResult(
                status=str(run["status"]),
                manifest_path=manifest_path,
                reviewed_path=reviewed_path,
                pending_path=pending_path,
                selection_manifest_path=selection_manifest,
                included=len(included_candidates),
                excluded=excluded,
                pending=len(pending_rows),
            )
        atomic_write_bytes(
            reviewed_path,
            reviewed_bytes,
        )
        _write_pending(pending_path, pending_rows)
        atomic_write_bytes(manifest_path, review_manifest_bytes)
        update_run_manifest(
            destination,
            phase="research-review",
            status=status,
            review_manifest=manifest_path.name,
            selection_manifest=(
                str(selection_manifest.relative_to(destination))
                if selection_manifest
                else None
            ),
        )
        return ResearchReviewResult(
            status=status,
            manifest_path=manifest_path,
            reviewed_path=reviewed_path,
            pending_path=pending_path,
            selection_manifest_path=selection_manifest,
            included=len(included_candidates),
            excluded=excluded,
            pending=len(pending_rows),
        )
