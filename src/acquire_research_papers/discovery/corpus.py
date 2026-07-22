from __future__ import annotations

import csv
import io
import json
import math
import re
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

from acquire_research_papers.artifacts import (
    atomic_write_bytes,
    sanitize_artifact_value,
    sha256_bytes,
)
from acquire_research_papers.discovery.contracts import (
    CandidateMetadata,
    CandidatePage,
    CoverageSlice,
    DiscoveryBatch,
    DiscoveryDiagnostic,
    DiscoveryRequest,
)
from acquire_research_papers.discovery.coordinator import candidate_identity, merge_candidates
from acquire_research_papers.discovery.evidence import EvidencePacket, evaluate_prefilter
from acquire_research_papers.models import PaperStatus

__all__ = ["CandidateMetadata", "CandidatePage"]


@dataclass(frozen=True)
class ScreeningDecision:
    candidate: CandidateMetadata
    status: PaperStatus
    reasons: tuple[str, ...]


class ScreeningGate:
    def __init__(self, *, auto_threshold: float = 0.85, review_threshold: float = 0.65) -> None:
        self.auto_threshold = auto_threshold
        self.review_threshold = review_threshold

    def decide(self, candidate: CandidateMetadata) -> ScreeningDecision:
        if not candidate.hard_gates_passed:
            return ScreeningDecision(candidate, PaperStatus.REJECTED, ("hard_gate_failed",))
        evidence = set(candidate.evidence_fields)
        has_auto_evidence = {"title", "abstract"}.issubset(evidence)
        if candidate.relevance_score >= self.auto_threshold and has_auto_evidence:
            return ScreeningDecision(candidate, PaperStatus.AUTO_ACCEPTED, ("high_confidence",))
        if candidate.relevance_score >= self.review_threshold:
            reasons = []
            if candidate.relevance_score < self.auto_threshold:
                reasons.append("relevance_below_auto_threshold")
            if not has_auto_evidence:
                reasons.append("insufficient_evidence_for_auto_accept")
            return ScreeningDecision(
                candidate,
                PaperStatus.PENDING_REVIEW,
                tuple(reasons or ["screening_ambiguous"]),
            )
        return ScreeningDecision(candidate, PaperStatus.REJECTED, ("relevance_below_review_threshold",))


@dataclass(frozen=True)
class CorpusPlan:
    auto_accepted: tuple[CandidateMetadata, ...]
    pending_review: tuple[CandidateMetadata, ...]
    rejected: tuple[CandidateMetadata, ...]
    not_selected: tuple[CandidateMetadata, ...]
    decisions: tuple[ScreeningDecision, ...]
    shortfall: int
    quota_shortfalls: tuple[str, ...] = ()


class CorpusPlanner:
    def __init__(self, spec: dict[str, Any], *, gate: ScreeningGate | None = None) -> None:
        self.spec = spec
        self.gate = gate or ScreeningGate()

    def _rank(self, candidate: CandidateMetadata) -> tuple[int, int, float, str]:
        priority = self.spec.get("scope", {}).get("years", {}).get("priority", [])
        year_rank = priority.index(candidate.year) if candidate.year in priority else len(priority)
        try:
            publication_rank = -date.fromisoformat(candidate.publication_date or "").toordinal()
        except ValueError:
            publication_rank = -candidate.year * 366
        return (year_rank, publication_rank, -candidate.relevance_score, candidate.key)

    @staticmethod
    def _matches_group(candidate: CandidateMetadata, group: dict[str, Any]) -> bool:
        venues = {str(value).casefold() for value in group.get("venues", [])}
        years = set(group.get("years", []))
        return (not venues or candidate.venue.casefold() in venues) and (
            not years or candidate.year in years
        )

    def _group_count(
        self,
        selected: list[CandidateMetadata],
        group: dict[str, Any],
    ) -> int:
        return sum(self._matches_group(candidate, group) for candidate in selected)

    def _can_add(
        self,
        selected: list[CandidateMetadata],
        candidate: CandidateMetadata,
    ) -> bool:
        for group in self.spec.get("quotas", {}).get("groups", []):
            group_maximum = group.get("maximum")
            if group_maximum is None or not self._matches_group(candidate, group):
                continue
            if self._group_count(selected, group) >= int(group_maximum):
                return False
        return True

    @staticmethod
    def _is_recent(candidate: CandidateMetadata, start: date) -> bool:
        if not candidate.publication_date:
            return False
        try:
            return date.fromisoformat(candidate.publication_date) >= start
        except ValueError:
            return False

    def select(self, candidates: Iterable[CandidateMetadata]) -> CorpusPlan:
        decisions = tuple(self.gate.decide(candidate) for candidate in candidates)
        auto_pool = sorted(
            (decision.candidate for decision in decisions if decision.status is PaperStatus.AUTO_ACCEPTED),
            key=self._rank,
        )
        pending = tuple(
            sorted(
                (
                    decision.candidate
                    for decision in decisions
                    if decision.status is PaperStatus.PENDING_REVIEW
                ),
                key=self._rank,
            )
        )
        rejected = tuple(
            sorted(
                (decision.candidate for decision in decisions if decision.status is PaperStatus.REJECTED),
                key=self._rank,
            )
        )
        target = self.spec.get("target", {})
        minimum = int(target.get("minimum", 0))
        preferred = int(target.get("preferred", target.get("maximum", len(auto_pool))))
        maximum = int(target.get("maximum", max(preferred, len(auto_pool))))
        goal = min(preferred, maximum)
        planned_total = min(goal, len(auto_pool))

        selected: list[CandidateMetadata] = []
        selected_keys: set[str] = set()
        groups = self.spec.get("quotas", {}).get("groups", [])

        def add(candidate: CandidateMetadata) -> bool:
            if (
                candidate.key in selected_keys
                or len(selected) >= maximum
                or not self._can_add(selected, candidate)
            ):
                return False
            selected.append(candidate)
            selected_keys.add(candidate.key)
            return True

        for group in groups:
            required = int(group.get("minimum", 0))
            for candidate in auto_pool:
                if self._group_count(selected, group) >= required:
                    break
                if self._matches_group(candidate, group):
                    add(candidate)

        recent_window = self.spec.get("quotas", {}).get("recent_window")
        recent_start: date | None = None
        recent_ratio = 0.0
        if recent_window:
            recent_start = date.fromisoformat(str(recent_window["from"]))
            recent_ratio = float(recent_window["minimum_ratio"])
            required_recent = math.ceil(planned_total * recent_ratio)
            for candidate in auto_pool:
                if sum(self._is_recent(item, recent_start) for item in selected) >= required_recent:
                    break
                if self._is_recent(candidate, recent_start):
                    add(candidate)

        for candidate in auto_pool:
            if len(selected) >= goal:
                break
            add(candidate)
        selected.sort(key=self._rank)
        overflow = tuple(candidate for candidate in auto_pool if candidate.key not in selected_keys)

        quota_shortfalls: list[str] = []
        for group in groups:
            missing = max(0, int(group.get("minimum", 0)) - self._group_count(selected, group))
            if missing:
                quota_shortfalls.append(f"group:{group.get('name', '')}:{missing}")
        if recent_start is not None:
            required_recent = math.ceil(len(selected) * recent_ratio)
            actual_recent = sum(self._is_recent(item, recent_start) for item in selected)
            if actual_recent < required_recent:
                quota_shortfalls.append(f"recent:{required_recent - actual_recent}")
        global_shortfall = max(0, minimum - len(selected))
        if global_shortfall:
            quota_shortfalls.append(f"global:{global_shortfall}")
        return CorpusPlan(
            auto_accepted=tuple(selected),
            pending_review=pending,
            rejected=rejected,
            not_selected=overflow,
            decisions=decisions,
            shortfall=global_shortfall,
            quota_shortfalls=tuple(quota_shortfalls),
        )

    def select_accepted(self, candidates: Iterable[CandidateMetadata]) -> CorpusPlan:
        """Apply quotas to candidates already accepted by semantic review."""
        accepted = (
            replace(candidate, relevance_score=1.0)
            for candidate in candidates
        )
        return self.select(accepted)


def _normalized(value: str) -> str:
    return " ".join(re.findall(r"\w+", value.casefold()))


class CorpusDiscoverer:
    """Conservative lexical gating over one or more candidate-only clients."""

    def __init__(self, searchers: Iterable[Callable[[str, int], Iterable[CandidateMetadata]]]) -> None:
        self.searchers = tuple(searchers)

    @staticmethod
    def _screen(candidate: CandidateMetadata, spec: dict[str, Any]) -> CandidateMetadata:
        scope = spec.get("scope", {})
        years = set(scope.get("years", {}).get("include", []))
        venue_records = scope.get("venues", [])
        normalized_venue = _normalized(candidate.venue)
        matching_venues = [
            record
            for record in venue_records
            if normalized_venue
            in {
                _normalized(name)
                for name in [record.get("name", ""), *record.get("aliases", [])]
                if name
            }
        ]
        publication_types = scope.get("publication_types", {})
        included_types = {_normalized(value) for value in publication_types.get("include", [])}
        excluded_types = {_normalized(value) for value in publication_types.get("exclude", [])}
        topics = scope.get("topics", {})
        include_terms = [*topics.get("include", []), *topics.get("synonyms", [])]
        prefilter = evaluate_prefilter(candidate, spec)
        if not include_terms:
            score = max(candidate.relevance_score, 0.85)
        elif any(signal.startswith("title:") for signal in prefilter.signals):
            score = max(candidate.relevance_score, 0.95)
        elif prefilter.signals:
            score = max(candidate.relevance_score, 0.86)
        else:
            score = min(candidate.relevance_score, 0.64)

        publication_type = _normalized(candidate.publication_type or "")
        hard_gates = candidate.hard_gates_passed
        hard_gates &= not years or candidate.year in years
        hard_gates &= not venue_records or bool(matching_venues)
        hard_gates &= not matching_venues or any(
            not record.get("years") or candidate.year in set(record.get("years", ()))
            for record in matching_venues
        )
        hard_gates &= not included_types or publication_type in included_types
        hard_gates &= publication_type not in excluded_types
        hard_gates &= not prefilter.exclusion_signals
        return replace(candidate, relevance_score=score, hard_gates_passed=hard_gates)

    def __call__(self, spec: dict[str, Any]) -> list[CandidateMetadata]:
        topic_scope = spec.get("scope", {}).get("topics", {})
        queries = list(topic_scope.get("include", [])) or [str(spec.get("name", ""))]
        rows = int(spec.get("target", {}).get("maximum", 100))
        discovered: dict[str, CandidateMetadata] = {}
        for query in queries:
            if not query.strip():
                continue
            for searcher in self.searchers:
                for candidate in searcher(query, rows):
                    screened = self._screen(candidate, spec)
                    previous = discovered.get(screened.key)
                    if previous is None or screened.relevance_score > previous.relevance_score:
                        discovered[screened.key] = screened
        return list(discovered.values())


@dataclass(frozen=True)
class CorpusDiscoveryResult:
    status: str
    candidates_path: Path
    evidence_path: Path
    pending_metadata_path: Path
    diagnostics_path: Path
    coverage_path: Path
    request_path: Path
    manifest_path: Path
    reviewable: int
    pending_metadata: int
    hard_gate_failed: int
    coverage_incomplete: int


class CorpusDiscoveryWorkflow:
    """Enumerate and prepare immutable evidence without freezing a selection."""

    def __init__(self, *, discoverer: Callable[[DiscoveryRequest], DiscoveryBatch]) -> None:
        self.discoverer = discoverer

    @staticmethod
    def _write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
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
        sanitized = sanitize_artifact_value(payload)
        atomic_write_bytes(
            path,
            (
                json.dumps(sanitized, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8"),
        )

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, Any]]:
        if not path.is_file():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    @staticmethod
    def _fingerprint(spec: dict[str, Any]) -> str:
        canonical = json.dumps(
            spec,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return sha256_bytes(canonical)

    @staticmethod
    def _safe_candidate(candidate: CandidateMetadata) -> CandidateMetadata:
        payload = sanitize_artifact_value(candidate.to_dict())
        assert isinstance(payload, dict)
        return CandidateMetadata.from_dict(payload)

    @staticmethod
    def _coverage_key(item: CoverageSlice) -> tuple[str, str, int]:
        return (item.provider_id, item.venue, item.year)

    def run(self, spec: dict[str, Any], output: Path) -> CorpusDiscoveryResult:
        destination = output.resolve()
        destination.mkdir(parents=True, exist_ok=True)
        request_path = destination / "request-spec.json"
        manifest_path = destination / "discovery-manifest.json"
        fingerprint = self._fingerprint(spec)
        if request_path.is_file():
            previous_spec = json.loads(request_path.read_text(encoding="utf-8"))
            if self._fingerprint(previous_spec) != fingerprint:
                raise ValueError("discovery output belongs to a different corpus specification")
        elif manifest_path.is_file():
            raise ValueError("discovery output contains an incompatible legacy run")
        else:
            self._write_json(request_path, spec)

        request = DiscoveryRequest.from_spec(spec)
        candidates_path = destination / "candidates.jsonl"
        coverage_path = destination / "coverage.jsonl"
        diagnostics_path = destination / "discovery-errors.jsonl"
        prior_candidates = tuple(
            CandidateMetadata.from_dict(record)
            for record in self._read_jsonl(candidates_path)
        )
        prior_coverage = tuple(
            CoverageSlice(**record) for record in self._read_jsonl(coverage_path)
        )
        prior_diagnostics = tuple(
            DiscoveryDiagnostic(**record) for record in self._read_jsonl(diagnostics_path)
        )
        prior_manifest = (
            json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest_path.is_file()
            else {}
        )
        prior_legacy = tuple(str(value) for value in prior_manifest.get("provider_coverage", ()))
        retryable_providers = {
            item.provider_id for item in prior_diagnostics if item.retryable
        }
        resumable_legacy = tuple(
            label
            for label in prior_legacy
            if label.split(":", 1)[0] not in retryable_providers
        )
        completed_slices = frozenset(
            (
                *resumable_legacy,
                *(item.label for item in prior_coverage if item.state == "complete"),
            )
        )
        prior_is_complete = bool(prior_manifest) and (
            prior_manifest.get("status") != "coverage_incomplete"
            and not any(item.state != "complete" for item in prior_coverage)
        )
        if prior_is_complete:
            batch = DiscoveryBatch()
        else:
            batch = self.discoverer(request.with_completed_slices(completed_slices))

        merged: dict[str, CandidateMetadata] = {}
        for candidate in (*prior_candidates, *batch.candidates):
            safe = self._safe_candidate(candidate)
            identity = candidate_identity(safe)
            merged[identity] = merge_candidates(merged.get(identity), safe)

        coverage_by_key = {
            self._coverage_key(item): item for item in prior_coverage
        }
        for item in batch.coverage:
            coverage_by_key[self._coverage_key(item)] = item
        coverage = tuple(
            sorted(coverage_by_key.values(), key=lambda item: self._coverage_key(item))
        )

        if prior_is_complete:
            diagnostics = prior_diagnostics
        else:
            rerun_keys = {self._coverage_key(item) for item in batch.coverage}
            diagnostics = tuple(
                item
                for item in prior_diagnostics
                if (item.provider_id, item.venue, item.year) not in rerun_keys
                and item.provider_id not in retryable_providers
            ) + batch.diagnostics

        legacy_coverage = tuple(
            dict.fromkeys((*resumable_legacy, *batch.covered_slices))
        )
        complete_labels = tuple(
            dict.fromkeys(
                (
                    *legacy_coverage,
                    *(item.label for item in coverage if item.state == "complete"),
                )
            )
        )

        candidate_records: list[dict[str, Any]] = []
        packets: list[EvidencePacket] = []
        pending_packets: list[EvidencePacket] = []
        hard_gate_failed = 0
        for candidate in sorted(merged.values(), key=candidate_identity):
            screened = CorpusDiscoverer._screen(candidate, spec)
            prefilter = evaluate_prefilter(screened, spec)
            packet = EvidencePacket.from_candidate(
                screened,
                prefilter_signals=prefilter.signals,
            )
            if not screened.hard_gates_passed:
                decision = "hard_gate_failed"
                reasons = ("hard_gate_failed", *prefilter.exclusion_signals)
                hard_gate_failed += 1
            elif packet.metadata_state != "ready":
                decision = "metadata_pending"
                reasons = (packet.metadata_state,)
                packets.append(packet)
                pending_packets.append(packet)
            else:
                decision = "review_required"
                reasons = ("semantic_review_required",)
                packets.append(packet)
            candidate_records.append(
                {
                    **screened.to_dict(),
                    "candidate_id": packet.candidate_id,
                    "metadata_state": packet.metadata_state,
                    "prefilter_signals": prefilter.signals,
                    "exclusion_signals": prefilter.exclusion_signals,
                    "decision": decision,
                    "reasons": reasons,
                }
            )
        candidates_path = destination / "candidates.jsonl"
        self._write_jsonl(candidates_path, candidate_records)

        evidence_path = destination / "evidence-packets.jsonl"
        self._write_jsonl(
            evidence_path,
            (packet.to_dict() for packet in sorted(packets, key=lambda item: item.candidate_id)),
        )

        pending_path = destination / "pending-metadata.csv"
        pending_buffer = io.StringIO(newline="")
        pending_writer = csv.writer(pending_buffer)
        pending_writer.writerow(
            [
                "candidate_id",
                "title",
                "year",
                "venue",
                "metadata_state",
                "missing_fields",
            ]
        )
        for packet in sorted(pending_packets, key=lambda item: item.candidate_id):
            missing_fields = []
            if not packet.title:
                missing_fields.append("title")
            if not packet.abstract:
                missing_fields.append("abstract")
            pending_writer.writerow(
                [
                    packet.candidate_id,
                    packet.title,
                    packet.year,
                    packet.venue,
                    packet.metadata_state,
                    ";".join(missing_fields),
                ]
            )
        atomic_write_bytes(pending_path, pending_buffer.getvalue().encode("utf-8-sig"))

        self._write_jsonl(diagnostics_path, (asdict(item) for item in diagnostics))
        self._write_jsonl(coverage_path, (item.to_dict() for item in coverage))

        coverage_incomplete = sum(item.state != "complete" for item in coverage)
        if diagnostics and not coverage:
            coverage_incomplete = max(1, coverage_incomplete)
        reviewable = sum(packet.metadata_state == "ready" for packet in packets)
        if coverage_incomplete:
            run_status = "coverage_incomplete"
        elif pending_packets:
            run_status = "metadata_pending"
        else:
            run_status = "review_required"
        manifest = {
            "schema_version": 2,
            "phase": "discovery",
            "status": run_status,
            "request_sha256": fingerprint,
            "candidate_count": len(candidate_records),
            "reviewable": reviewable,
            "pending_metadata": len(pending_packets),
            "hard_gate_failed": hard_gate_failed,
            "coverage_incomplete": coverage_incomplete,
            "discovery_errors": len(diagnostics),
            "provider_coverage": list(complete_labels),
            "request": request_path.name,
            "coverage": coverage_path.name,
            "candidates": candidates_path.name,
            "evidence_packets": evidence_path.name,
            "pending_metadata_file": pending_path.name,
            "discovery_errors_file": diagnostics_path.name,
        }
        self._write_json(manifest_path, manifest)
        return CorpusDiscoveryResult(
            status=run_status,
            candidates_path=candidates_path,
            evidence_path=evidence_path,
            pending_metadata_path=pending_path,
            diagnostics_path=diagnostics_path,
            coverage_path=coverage_path,
            request_path=request_path,
            manifest_path=manifest_path,
            reviewable=reviewable,
            pending_metadata=len(pending_packets),
            hard_gate_failed=hard_gate_failed,
            coverage_incomplete=coverage_incomplete,
        )
