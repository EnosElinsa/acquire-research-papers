from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from acquire_research_papers.artifacts import (
    atomic_write_bytes,
    sanitize_artifact_value,
    sha256_bytes,
    sha256_file,
)
from acquire_research_papers.discovery.contracts import CandidateMetadata, DiscoveryRequest
from acquire_research_papers.discovery.corpus import CorpusPlanner
from acquire_research_papers.discovery.evidence import EvidencePacket
from acquire_research_papers.selection import (
    SelectionStore,
    build_selection_records,
)


class ReviewValidationError(ValueError):
    """A review decision is stale, ambiguous, or unsupported by its evidence packet."""


@dataclass(frozen=True)
class SemanticReviewRecord:
    candidate_id: str
    evidence_hash: str
    decision: Literal["accept", "reject", "pending"]
    matched_topics: tuple[str, ...]
    evidence_fields: tuple[str, ...]
    reason: str
    reviewer: str
    rule_version: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SemanticReviewRecord:
        allowed = {
            "candidate_id",
            "evidence_hash",
            "decision",
            "matched_topics",
            "evidence_fields",
            "reason",
            "reviewer",
            "rule_version",
        }
        if set(payload) - allowed:
            raise ReviewValidationError("review record contains unknown fields")
        missing = allowed - set(payload)
        if missing:
            raise ReviewValidationError(
                f"review record is missing required fields: {sorted(missing)}"
            )
        decision = str(payload["decision"])
        if decision not in {"accept", "reject", "pending"}:
            raise ReviewValidationError("review decision must be accept, reject, or pending")
        return cls(
            candidate_id=str(payload["candidate_id"]),
            evidence_hash=str(payload["evidence_hash"]),
            decision=decision,  # type: ignore[arg-type]
            matched_topics=tuple(str(value) for value in payload["matched_topics"]),
            evidence_fields=tuple(str(value) for value in payload["evidence_fields"]),
            reason=str(payload["reason"]).strip(),
            reviewer=str(payload["reviewer"]).strip(),
            rule_version=str(payload["rule_version"]).strip(),
        )


@dataclass(frozen=True)
class CorpusReviewResult:
    status: str
    reviewed_path: Path
    pending_review_path: Path
    selected_path: Path
    selection_manifest_path: Path
    manifest_path: Path
    accepted: int
    rejected: int
    pending: int
    ready_unreviewed: int
    review_completion: str
    selected: int
    shortfall_classes: tuple[str, ...]
    quota_shortfalls: tuple[str, ...]


class CorpusReviewWorkflow:
    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, Any]]:
        try:
            return [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ReviewValidationError(f"could not read review artifact: {path.name}") from exc

    @staticmethod
    def _write_jsonl(path: Path, records) -> None:
        payload = "".join(
            json.dumps(
                sanitize_artifact_value(record),
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
            for record in records
        )
        atomic_write_bytes(path, payload.encode("utf-8"))

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        atomic_write_bytes(
            path,
            (
                json.dumps(
                    sanitize_artifact_value(payload),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8"),
        )

    @staticmethod
    def _validate_record(
        record: SemanticReviewRecord,
        packet: EvidencePacket,
    ) -> None:
        if record.evidence_hash != packet.evidence_hash:
            raise ReviewValidationError(
                f"review evidence hash does not match candidate {record.candidate_id}"
            )
        if not record.reason:
            raise ReviewValidationError("review reason is required")
        if record.reviewer.casefold() != "codex":
            raise ReviewValidationError("reviewer must be codex")
        if not record.rule_version:
            raise ReviewValidationError("review rule_version is required")
        if not record.evidence_fields:
            raise ReviewValidationError("review evidence_fields are required")
        allowed_fields = {"title", "abstract", "keywords"}
        supplied_fields = set(record.evidence_fields)
        if not supplied_fields.issubset(allowed_fields) or not supplied_fields.issubset(
            packet.evidence_fields
        ):
            raise ReviewValidationError("review evidence_fields are not present in the packet")
        if record.decision == "accept":
            if packet.metadata_state != "ready" or not packet.hard_gates_passed:
                raise ReviewValidationError("candidate metadata is not eligible for acceptance")
            if not record.matched_topics:
                raise ReviewValidationError("accepted review matched_topics are required")
            if not {"title", "abstract"}.issubset(supplied_fields):
                raise ReviewValidationError("acceptance must cite title and abstract evidence")
        elif packet.metadata_state != "ready" and record.decision != "pending":
            raise ReviewValidationError("candidate with incomplete metadata must remain pending")

    @staticmethod
    def _load_existing(
        root: Path,
        decision_sha256: str,
        discovery_manifest_sha256: str,
        request_sha256: str,
    ) -> CorpusReviewResult | None:
        manifest_path = root / "review-manifest.json"
        if not manifest_path.is_file():
            return None
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ReviewValidationError("existing review manifest could not be read") from exc
        if manifest.get("decision_sha256") != decision_sha256:
            raise ReviewValidationError(
                "review decisions are already frozen; start a new discovery run"
            )
        if manifest.get("discovery_manifest_sha256") != discovery_manifest_sha256:
            raise ReviewValidationError(
                "review discovery lineage changed; start a new discovery run"
            )
        selection_manifest_path = root / "selection-manifest.json"
        try:
            if sha256_file(selection_manifest_path) != manifest.get(
                "selection_manifest_sha256"
            ):
                raise ValueError("selection manifest hash mismatch")
            selection = SelectionStore.load(selection_manifest_path)
        except (OSError, ValueError) as exc:
            raise ReviewValidationError(
                "existing frozen selection failed validation"
            ) from exc
        if (
            selection.manifest.get("selected_sha256")
            != manifest.get("selected_sha256")
            or selection.manifest.get("spec_sha256") != request_sha256
            or selection.manifest.get("review_decision_sha256") != decision_sha256
            or selection.manifest.get("discovery_manifest_sha256")
            != discovery_manifest_sha256
            or len(selection.records) != int(manifest.get("selected", -1))
        ):
            raise ReviewValidationError(
                "existing frozen selection failed validation"
            )
        reviewed_path = root / "reviewed-candidates.jsonl"
        pending_review_path = root / "pending-review.csv"
        try:
            audit_hashes_match = (
                sha256_file(reviewed_path)
                == manifest.get("reviewed_candidates_sha256")
                and sha256_file(pending_review_path)
                == manifest.get("pending_review_sha256")
            )
        except OSError as exc:
            raise ReviewValidationError(
                "existing review audit artifact failed validation"
            ) from exc
        if not audit_hashes_match:
            raise ReviewValidationError(
                "existing review audit artifact failed validation"
            )
        return CorpusReviewResult(
            status=str(manifest["status"]),
            reviewed_path=reviewed_path,
            pending_review_path=pending_review_path,
            selected_path=selection.selected_path,
            selection_manifest_path=selection.manifest_path,
            manifest_path=manifest_path,
            accepted=int(manifest["accepted"]),
            rejected=int(manifest["rejected"]),
            pending=int(manifest["pending"]),
            ready_unreviewed=int(manifest.get("ready_unreviewed", 0)),
            review_completion=str(manifest.get("review_completion", "complete")),
            selected=int(manifest["selected"]),
            shortfall_classes=tuple(manifest["shortfall_classes"]),
            quota_shortfalls=tuple(manifest["quota_shortfalls"]),
        )

    def run(self, run: Path, decisions: Path) -> CorpusReviewResult:
        root = run.resolve()
        decisions_path = decisions.resolve()
        discovery_manifest_path = root / "discovery-manifest.json"
        request_path = root / "request-spec.json"
        evidence_path = root / "evidence-packets.jsonl"
        candidates_path = root / "candidates.jsonl"
        try:
            discovery_manifest = json.loads(
                discovery_manifest_path.read_text(encoding="utf-8")
            )
            spec = json.loads(request_path.read_text(encoding="utf-8"))
            decision_bytes = decisions_path.read_bytes()
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ReviewValidationError("review run is missing required discovery artifacts") from exc
        if discovery_manifest.get("schema_version") != 2:
            raise ReviewValidationError("review requires a schema version 2 discovery run")
        request_sha256 = sha256_bytes(
            json.dumps(
                spec,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        if discovery_manifest.get("request_sha256") != request_sha256:
            raise ReviewValidationError("discovery request hash validation failed")
        artifact_hashes = (
            (candidates_path, "candidates_sha256", "candidates"),
            (evidence_path, "evidence_packets_sha256", "evidence packets"),
            (root / "coverage.jsonl", "coverage_sha256", "coverage"),
        )
        for artifact_path, field, label in artifact_hashes:
            try:
                digest = sha256_file(artifact_path)
            except OSError as exc:
                raise ReviewValidationError(
                    f"discovery {label} artifact could not be read"
                ) from exc
            if discovery_manifest.get(field) != digest:
                raise ReviewValidationError(
                    f"discovery {label} hash validation failed"
                )
        discovery_manifest_sha256 = sha256_file(discovery_manifest_path)
        decision_sha256 = sha256_bytes(decision_bytes)
        existing = self._load_existing(
            root,
            decision_sha256,
            discovery_manifest_sha256,
            request_sha256,
        )
        if existing is not None:
            return existing

        candidate_by_id: dict[str, CandidateMetadata] = {}
        for payload in self._read_jsonl(candidates_path):
            candidate_id = str(payload.get("candidate_id", ""))
            if candidate_id:
                candidate_by_id[candidate_id] = CandidateMetadata.from_dict(payload)

        packet_by_id: dict[str, EvidencePacket] = {}
        for payload in self._read_jsonl(evidence_path):
            packet = EvidencePacket.from_dict(payload)
            if packet.candidate_id in packet_by_id:
                raise ReviewValidationError("duplicate candidate in evidence packets")
            candidate = candidate_by_id.get(packet.candidate_id)
            if candidate is None:
                raise ReviewValidationError("evidence packet references an unknown candidate")
            expected = EvidencePacket.from_candidate(
                candidate,
                prefilter_signals=packet.prefilter_signals,
            )
            if expected.evidence_hash != packet.evidence_hash:
                raise ReviewValidationError("evidence packet hash validation failed")
            packet_by_id[packet.candidate_id] = packet

        decision_by_id: dict[str, SemanticReviewRecord] = {}
        for payload in self._read_jsonl(decisions_path):
            record = SemanticReviewRecord.from_dict(payload)
            if record.candidate_id in decision_by_id:
                raise ReviewValidationError("duplicate review decision")
            packet = packet_by_id.get(record.candidate_id)
            if packet is None:
                raise ReviewValidationError("review decision references an unknown candidate")
            self._validate_record(record, packet)
            decision_by_id[record.candidate_id] = record

        accepted_candidates: list[CandidateMetadata] = []
        reviewed_records: list[dict[str, Any]] = []
        pending_rows: list[tuple[EvidencePacket, str]] = []
        accepted = rejected = pending = 0
        ready_pending = 0
        ready_unreviewed = 0
        metadata_pending = 0
        for candidate_id, packet in sorted(packet_by_id.items()):
            record = decision_by_id.get(candidate_id)
            if record is None:
                decision = "pending"
                reason = (
                    "metadata_incomplete"
                    if packet.metadata_state != "ready"
                    else "decision_missing"
                )
                matched_topics: tuple[str, ...] = ()
                evidence_fields: tuple[str, ...] = ()
                reviewer = ""
                rule_version = ""
            else:
                decision = record.decision
                reason = record.reason
                matched_topics = record.matched_topics
                evidence_fields = record.evidence_fields
                reviewer = record.reviewer
                rule_version = record.rule_version
            if decision == "accept":
                accepted += 1
                accepted_candidates.append(candidate_by_id[candidate_id])
            elif decision == "reject":
                rejected += 1
            else:
                pending += 1
                pending_rows.append((packet, reason))
                if packet.metadata_state != "ready":
                    metadata_pending += 1
                else:
                    ready_pending += 1
                    if record is None:
                        ready_unreviewed += 1
            reviewed_records.append(
                {
                    **packet.to_dict(),
                    "review": {
                        "decision": decision,
                        "matched_topics": matched_topics,
                        "evidence_fields": evidence_fields,
                        "reason": reason,
                        "reviewer": reviewer,
                        "rule_version": rule_version,
                    },
                }
            )

        request = DiscoveryRequest.from_spec(spec)
        plan = CorpusPlanner(spec).select_accepted(accepted_candidates)
        selected_records = build_selection_records(
            plan.auto_accepted,
            venues=request.venues,
            delivery=spec.get("delivery", {}),
        )
        shortfall_classes: list[str] = []
        if int(discovery_manifest.get("coverage_incomplete", 0)):
            shortfall_classes.append("coverage")
        target = spec.get("target", {})
        preferred = int(target.get("preferred", target.get("maximum", 0)))
        maximum = int(target.get("maximum", preferred))
        preferred_goal = min(preferred, maximum)
        early_stop_satisfied = (
            len(selected_records) >= preferred_goal
            and not plan.shortfall
            and not plan.quota_shortfalls
        )
        if not ready_pending:
            review_completion = "complete"
        elif early_stop_satisfied:
            review_completion = "target_satisfied_early_stop"
        else:
            review_completion = "incomplete"
        unresolved_candidates_may_fill_shortfall = bool(
            plan.shortfall
            or plan.quota_shortfalls
            or review_completion == "incomplete"
        )
        if unresolved_candidates_may_fill_shortfall:
            if metadata_pending:
                shortfall_classes.append("evidence")
            if ready_pending:
                shortfall_classes.append("review")
        if plan.quota_shortfalls:
            shortfall_classes.append("quota")
        status = "shortfall" if shortfall_classes else "frozen"

        selection = SelectionStore.write(
            root,
            spec,
            selected_records,
            discovery_summary={
                "provider_coverage": discovery_manifest.get("provider_coverage", []),
                "discovery_errors": discovery_manifest.get("discovery_errors", 0),
                "review_decision_sha256": decision_sha256,
                "discovery_manifest_sha256": discovery_manifest_sha256,
                "quota_shortfalls": list(plan.quota_shortfalls),
                "shortfall_classes": shortfall_classes,
            },
        )
        reviewed_path = root / "reviewed-candidates.jsonl"
        self._write_jsonl(reviewed_path, reviewed_records)
        pending_review_path = root / "pending-review.csv"
        pending_buffer = io.StringIO(newline="")
        writer = csv.writer(pending_buffer)
        writer.writerow(
            ["candidate_id", "title", "year", "venue", "metadata_state", "reason"]
        )
        for packet, reason in pending_rows:
            writer.writerow(
                [
                    packet.candidate_id,
                    packet.title,
                    packet.year,
                    packet.venue,
                    packet.metadata_state,
                    reason,
                ]
            )
        atomic_write_bytes(
            pending_review_path,
            pending_buffer.getvalue().encode("utf-8-sig"),
        )

        manifest_path = root / "review-manifest.json"
        manifest = {
            "schema_version": 1,
            "phase": "review",
            "status": status,
            "decision_sha256": decision_sha256,
            "discovery_manifest_sha256": discovery_manifest_sha256,
            "selection_manifest_sha256": sha256_file(selection.manifest_path),
            "selected_sha256": selection.manifest["selected_sha256"],
            "accepted": accepted,
            "rejected": rejected,
            "pending": pending,
            "ready_unreviewed": ready_unreviewed,
            "review_completion": review_completion,
            "selected": len(selected_records),
            "shortfall_classes": shortfall_classes,
            "quota_shortfalls": list(plan.quota_shortfalls),
            "reviewed_candidates": reviewed_path.name,
            "reviewed_candidates_sha256": sha256_file(reviewed_path),
            "pending_review": pending_review_path.name,
            "pending_review_sha256": sha256_file(pending_review_path),
            "selected_papers": selection.selected_path.name,
            "selection_manifest": selection.manifest_path.name,
        }
        self._write_json(manifest_path, manifest)
        return CorpusReviewResult(
            status=status,
            reviewed_path=reviewed_path,
            pending_review_path=pending_review_path,
            selected_path=selection.selected_path,
            selection_manifest_path=selection.manifest_path,
            manifest_path=manifest_path,
            accepted=accepted,
            rejected=rejected,
            pending=pending,
            ready_unreviewed=ready_unreviewed,
            review_completion=review_completion,
            selected=len(selected_records),
            shortfall_classes=tuple(shortfall_classes),
            quota_shortfalls=plan.quota_shortfalls,
        )
