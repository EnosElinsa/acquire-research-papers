from __future__ import annotations

import csv
import io
import json
import re
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from acquire_research_papers.artifacts import atomic_write_bytes
from acquire_research_papers.models import PaperStatus


@dataclass(frozen=True)
class CandidateMetadata:
    key: str
    title: str
    year: int
    venue: str
    relevance_score: float
    hard_gates_passed: bool
    evidence_fields: tuple[str, ...]
    doi: str | None = None
    official_url: str | None = None
    authors: tuple[str, ...] = ()
    abstract: str = ""
    publication_type: str | None = None
    publication_date: str | None = None
    citation_count: int = 0
    related_ids: tuple[str, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CandidatePage:
    candidates: tuple[CandidateMetadata, ...]
    next_cursor: str | None = None


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


class CorpusPlanner:
    def __init__(self, spec: dict[str, Any], *, gate: ScreeningGate | None = None) -> None:
        self.spec = spec
        self.gate = gate or ScreeningGate()

    def _rank(self, candidate: CandidateMetadata) -> tuple[int, int, float, str]:
        priority = self.spec.get("scope", {}).get("years", {}).get("priority", [])
        year_rank = priority.index(candidate.year) if candidate.year in priority else len(priority)
        return (year_rank, -candidate.year, -candidate.relevance_score, candidate.key)

    @staticmethod
    def _matches_group(candidate: CandidateMetadata, group: dict[str, Any]) -> bool:
        venues = {str(value).casefold() for value in group.get("venues", [])}
        years = set(group.get("years", []))
        return (not venues or candidate.venue.casefold() in venues) and (
            not years or candidate.year in years
        )

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

        selected: list[CandidateMetadata] = []
        selected_keys: set[str] = set()
        for group in self.spec.get("quotas", {}).get("groups", []):
            required = int(group.get("minimum", 0))
            eligible = [
                candidate
                for candidate in auto_pool
                if candidate.key not in selected_keys and self._matches_group(candidate, group)
            ]
            for candidate in eligible[:required]:
                if len(selected) >= maximum:
                    break
                selected.append(candidate)
                selected_keys.add(candidate.key)

        for candidate in auto_pool:
            if len(selected) >= goal:
                break
            if candidate.key not in selected_keys:
                selected.append(candidate)
                selected_keys.add(candidate.key)
        selected.sort(key=self._rank)
        overflow = tuple(candidate for candidate in auto_pool if candidate.key not in selected_keys)
        return CorpusPlan(
            auto_accepted=tuple(selected),
            pending_review=pending,
            rejected=rejected,
            not_selected=overflow,
            decisions=decisions,
            shortfall=max(0, minimum - len(selected)),
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
class CorpusRunResult:
    status: str
    candidates_path: Path
    pending_review_path: Path
    manifest_path: Path
    accepted: int
    pending: int
    rejected: int
    shortfall: int


class CorpusWorkflow:
    def __init__(self, *, discoverer: Callable[[dict[str, Any]], Iterable[CandidateMetadata]]) -> None:
        self.discoverer = discoverer

    def run(self, spec: dict[str, Any], output: Path) -> CorpusRunResult:
        destination = output.resolve()
        destination.mkdir(parents=True, exist_ok=True)
        candidates = list(self.discoverer(spec))
        plan = CorpusPlanner(spec).select(candidates)
        decision_by_key = {decision.candidate.key: decision for decision in plan.decisions}
        selected_keys = {candidate.key for candidate in plan.auto_accepted}
        records = []
        for candidate in sorted(candidates, key=lambda item: item.key):
            decision = decision_by_key[candidate.key]
            status = decision.status.value
            if decision.status is PaperStatus.AUTO_ACCEPTED and candidate.key not in selected_keys:
                status = "not_selected"
            records.append(
                {
                    **candidate.to_dict(),
                    "decision": status,
                    "reasons": decision.reasons,
                }
            )
        candidates_path = destination / "candidates.jsonl"
        candidates_text = "".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records
        )
        atomic_write_bytes(candidates_path, candidates_text.encode("utf-8"))

        pending_path = destination / "pending-review.csv"
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)
        writer.writerow(["key", "title", "year", "venue", "relevance_score", "reasons"])
        for candidate in plan.pending_review:
            reasons = decision_by_key[candidate.key].reasons
            writer.writerow(
                [
                    candidate.key,
                    candidate.title,
                    candidate.year,
                    candidate.venue,
                    f"{candidate.relevance_score:.4f}",
                    ";".join(reasons),
                ]
            )
        atomic_write_bytes(pending_path, buffer.getvalue().encode("utf-8-sig"))

        manifest_path = destination / "corpus-manifest.json"
        manifest = {
            "status": "shortfall" if plan.shortfall else "planned",
            "accepted": len(plan.auto_accepted),
            "pending": len(plan.pending_review),
            "rejected": len(plan.rejected),
            "not_selected": len(plan.not_selected),
            "shortfall": plan.shortfall,
        }
        atomic_write_bytes(
            manifest_path,
            (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )
        return CorpusRunResult(
            status=str(manifest["status"]),
            candidates_path=candidates_path,
            pending_review_path=pending_path,
            manifest_path=manifest_path,
            accepted=int(manifest["accepted"]),
            pending=int(manifest["pending"]),
            rejected=int(manifest["rejected"]),
            shortfall=int(manifest["shortfall"]),
        )
