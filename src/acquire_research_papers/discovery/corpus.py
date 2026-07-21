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

from acquire_research_papers.artifacts import atomic_write_bytes
from acquire_research_papers.discovery.contracts import (
    CandidateMetadata,
    CandidatePage,
    DiscoveryBatch,
    DiscoveryRequest,
)
from acquire_research_papers.models import PaperStatus
from acquire_research_papers.selection import SelectionStore, build_selection_records

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
        venue_names = {
            _normalized(name)
            for record in venue_records
            for name in [record.get("name", ""), *record.get("aliases", [])]
            if name
        }
        publication_types = scope.get("publication_types", {})
        included_types = {_normalized(value) for value in publication_types.get("include", [])}
        excluded_types = {_normalized(value) for value in publication_types.get("exclude", [])}
        topics = scope.get("topics", {})
        include_terms = [
            _normalized(value)
            for value in [*topics.get("include", []), *topics.get("synonyms", [])]
            if value
        ]
        exclude_terms = [_normalized(value) for value in topics.get("exclude", []) if value]

        haystack = _normalized(f"{candidate.title} {candidate.abstract}")
        title = _normalized(candidate.title)
        topic_title = any(term and term in title for term in include_terms)
        topic_body = any(term and term in haystack for term in include_terms)
        excluded_topic = any(term and term in haystack for term in exclude_terms)
        if not include_terms:
            score = max(candidate.relevance_score, 0.85)
        elif topic_title:
            score = max(candidate.relevance_score, 0.95)
        elif topic_body:
            score = max(candidate.relevance_score, 0.86)
        else:
            score = min(candidate.relevance_score, 0.64)

        publication_type = _normalized(candidate.publication_type or "")
        hard_gates = candidate.hard_gates_passed
        hard_gates &= not years or candidate.year in years
        hard_gates &= not venue_names or _normalized(candidate.venue) in venue_names
        hard_gates &= not included_types or publication_type in included_types
        hard_gates &= publication_type not in excluded_types
        hard_gates &= not excluded_topic
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
    selected_path: Path
    pending_review_path: Path
    diagnostics_path: Path
    selection_manifest_path: Path
    manifest_path: Path
    accepted: int
    pending: int
    rejected: int
    not_selected: int
    shortfall: int
    quota_shortfalls: tuple[str, ...]


class CorpusDiscoveryWorkflow:
    """Discover, screen, and freeze a corpus without acquiring artifacts."""

    def __init__(self, *, discoverer: Callable[[DiscoveryRequest], DiscoveryBatch]) -> None:
        self.discoverer = discoverer

    @staticmethod
    def _write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
        payload = "".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
            for record in records
        )
        atomic_write_bytes(path, payload.encode("utf-8"))

    def run(self, spec: dict[str, Any], output: Path) -> CorpusDiscoveryResult:
        destination = output.resolve()
        destination.mkdir(parents=True, exist_ok=True)
        request = DiscoveryRequest.from_spec(spec)
        batch = self.discoverer(request)
        candidates = [CorpusDiscoverer._screen(item, spec) for item in batch.candidates]
        plan = CorpusPlanner(spec).select(candidates)
        decision_by_key = {decision.candidate.key: decision for decision in plan.decisions}
        selected_keys = {candidate.key for candidate in plan.auto_accepted}

        candidate_records: list[dict[str, Any]] = []
        for candidate in sorted(candidates, key=lambda item: item.key):
            decision = decision_by_key[candidate.key]
            status = decision.status.value
            if decision.status is PaperStatus.AUTO_ACCEPTED and candidate.key not in selected_keys:
                status = "not_selected"
            candidate_records.append(
                {
                    **candidate.to_dict(),
                    "decision": status,
                    "reasons": decision.reasons,
                }
            )
        candidates_path = destination / "candidates.jsonl"
        self._write_jsonl(candidates_path, candidate_records)

        pending_path = destination / "pending-review.csv"
        pending_buffer = io.StringIO(newline="")
        pending_writer = csv.writer(pending_buffer)
        pending_writer.writerow(
            ["key", "title", "year", "venue", "relevance_score", "reasons"]
        )
        for candidate in plan.pending_review:
            reasons = decision_by_key[candidate.key].reasons
            pending_writer.writerow(
                [
                    candidate.key,
                    candidate.title,
                    candidate.year,
                    candidate.venue,
                    f"{candidate.relevance_score:.4f}",
                    ";".join(reasons),
                ]
            )
        atomic_write_bytes(pending_path, pending_buffer.getvalue().encode("utf-8-sig"))

        diagnostics_path = destination / "discovery-errors.jsonl"
        self._write_jsonl(diagnostics_path, (asdict(item) for item in batch.diagnostics))

        selected_records = build_selection_records(
            plan.auto_accepted,
            venues=request.venues,
            delivery=spec["delivery"],
        )
        selection = SelectionStore.write(
            destination,
            spec,
            selected_records,
            discovery_summary={
                "provider_coverage": list(batch.covered_slices),
                "discovery_errors": len(batch.diagnostics),
                "quota_shortfalls": list(plan.quota_shortfalls),
            },
        )

        run_status = "shortfall" if plan.quota_shortfalls else "planned"
        manifest_path = destination / "corpus-manifest.json"
        manifest = {
            "schema_version": 1,
            "phase": "discovery",
            "status": run_status,
            "accepted": len(plan.auto_accepted),
            "pending": len(plan.pending_review),
            "rejected": len(plan.rejected),
            "not_selected": len(plan.not_selected),
            "shortfall": plan.shortfall,
            "quota_shortfalls": list(plan.quota_shortfalls),
            "discovery_errors": len(batch.diagnostics),
            "provider_coverage": list(batch.covered_slices),
            "candidates": candidates_path.name,
            "selected": selection.selected_path.name,
            "pending_review": pending_path.name,
            "discovery_errors_file": diagnostics_path.name,
            "selection_manifest": selection.manifest_path.name,
        }
        atomic_write_bytes(
            manifest_path,
            (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
                "utf-8"
            ),
        )
        return CorpusDiscoveryResult(
            status=run_status,
            candidates_path=candidates_path,
            selected_path=selection.selected_path,
            pending_review_path=pending_path,
            diagnostics_path=diagnostics_path,
            selection_manifest_path=selection.manifest_path,
            manifest_path=manifest_path,
            accepted=len(plan.auto_accepted),
            pending=len(plan.pending_review),
            rejected=len(plan.rejected),
            not_selected=len(plan.not_selected),
            shortfall=plan.shortfall,
            quota_shortfalls=plan.quota_shortfalls,
        )
