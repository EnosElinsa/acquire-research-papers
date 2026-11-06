from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from functools import partial
from typing import Any

from acquire_research_papers.discovery.contracts import (
    CandidateMetadata,
    CoverageSlice,
    DiscoveryBatch,
    DiscoveryDiagnostic,
    DiscoveryEnricher,
    DiscoveryProvider,
    DiscoveryRequest,
    VenueScope,
)
from acquire_research_papers.http import HttpStatusError, NetworkTransient, RateLimited
from acquire_research_papers.models import normalize_doi


class CandidateConflict(ValueError):
    """Two records sharing a discovery identity disagree on a hard identity field."""


class ProviderTimeout(RuntimeError):
    """A provider did not finish within the time limit of this discovery."""


_METADATA_SOURCES = frozenset({"crossref", "openalex", "semantic-scholar"})
_SAFE_PROVIDER_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
# Providers that list whole venues. Without a requested venue they would list every paper of
# their archive (all ACL or IJCAI papers of each year), so they only run for named venues.
_VENUE_SCOPED = frozenset({"official_index", "venue_enumerator"})
_JOIN_SECONDS = 0.5


def _call_bounded(function: Callable[[], Any], timeout_seconds: float | None,
                  monotonic: Callable[[], float]) -> Any:
    """Run ``function`` in a helper thread while the caller stays responsive to Ctrl+C.

    The caller waits in short joins, so a stop request (KeyboardInterrupt) or the time limit
    takes effect within half a second even while the provider blocks on the network. An
    abandoned daemon thread ends with the process; its late result is ignored.
    """
    outcome: dict[str, Any] = {}

    def target() -> None:
        try:
            outcome["value"] = function()
        except BaseException as exc:  # handed to the caller below
            outcome["error"] = exc

    worker = threading.Thread(target=target, name="arp-discovery-provider", daemon=True)
    worker.start()
    deadline = None if timeout_seconds is None else monotonic() + timeout_seconds
    while worker.is_alive():
        wait = _JOIN_SECONDS
        if deadline is not None:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise ProviderTimeout()
            wait = min(wait, remaining)
        worker.join(wait)
    if "error" in outcome:
        raise outcome["error"]
    return outcome.get("value")


def _run_side_by_side(
    functions: list[Callable[[], Any]], timeout_seconds: float | None,
    monotonic: Callable[[], float],
) -> tuple[list[tuple[str, Any] | None], bool]:
    """Run ``functions`` at once; each outcome is ("ok", value), ("error", exception), or
    ("timeout", None) after the shared time limit. A stop request (KeyboardInterrupt) returns
    at once with ``None`` for the unfinished ones and ``True`` as the second value."""
    results: list[tuple[str, Any] | None] = [None] * len(functions)

    def target(index: int, function: Callable[[], Any]) -> None:
        try:
            results[index] = ("ok", function())
        except BaseException as exc:  # handed to the caller
            results[index] = ("error", exc)

    workers = [threading.Thread(target=target, args=(index, function), daemon=True,
                                name="arp-discovery-search")
               for index, function in enumerate(functions)]
    for worker in workers:
        worker.start()
    deadline = None if timeout_seconds is None else monotonic() + timeout_seconds
    try:
        while any(worker.is_alive() for worker in workers):
            wait = _JOIN_SECONDS
            if deadline is not None:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    break
                wait = min(wait, remaining)
            next(worker for worker in workers if worker.is_alive()).join(wait)
    except KeyboardInterrupt:
        return list(results), True
    return [result if result is not None else ("timeout", None) for result in results], False


def _normalized(value: str) -> str:
    return " ".join(re.findall(r"\w+", value.casefold()))


def candidate_identity(candidate: CandidateMetadata) -> str:
    if candidate.doi:
        return f"doi:{normalize_doi(candidate.doi)}"
    if candidate.official_url:
        return f"url:{candidate.official_url.rstrip('/').casefold()}"
    return "meta:" + "|".join(
        (_normalized(candidate.title), str(candidate.year), _normalized(candidate.venue))
    )


def _source(candidate: CandidateMetadata) -> str:
    return str(candidate.provenance.get("source", ""))


def _is_official(candidate: CandidateMetadata) -> bool:
    source = _source(candidate)
    return bool(source and source not in _METADATA_SOURCES)


def _pick(previous: CandidateMetadata, current: CandidateMetadata, field: str):
    old = getattr(previous, field)
    new = getattr(current, field)
    if new and (not old or (_is_official(current) and not _is_official(previous))):
        return new
    return old


def _field_sources(candidate: CandidateMetadata) -> dict[str, tuple[str, ...]]:
    fields = dict(candidate.field_provenance)
    source = _source(candidate)
    if source:
        for field in candidate.evidence_fields:
            fields.setdefault(field, (source,))
    return fields


def _source_records(candidate: CandidateMetadata) -> tuple[dict[str, object], ...]:
    if candidate.source_records:
        return candidate.source_records
    if candidate.provenance:
        return (dict(candidate.provenance),)
    return ()


def _merged_source_records(
    previous: CandidateMetadata,
    current: CandidateMetadata,
) -> tuple[dict[str, object], ...]:
    records: list[dict[str, object]] = []
    for record in (*_source_records(previous), *_source_records(current)):
        if record not in records:
            records.append(record)
    return tuple(records)


def merge_candidates(
    previous: CandidateMetadata | None,
    current: CandidateMetadata,
) -> CandidateMetadata:
    if previous is None:
        return replace(
            current,
            field_provenance=_field_sources(current),
            source_records=_source_records(current),
        )
    if previous.doi and current.doi and normalize_doi(previous.doi) != normalize_doi(current.doi):
        raise CandidateConflict("conflicting DOI")
    same_doi = bool(
        previous.doi
        and current.doi
        and normalize_doi(previous.doi) == normalize_doi(current.doi)
    )
    if previous.year and current.year and previous.year != current.year and not same_doi:
        raise CandidateConflict("conflicting year")

    field_provenance: dict[str, tuple[str, ...]] = {}
    previous_fields = _field_sources(previous)
    current_fields = _field_sources(current)
    for key in previous_fields.keys() | current_fields.keys():
        field_provenance[key] = tuple(
            dict.fromkeys((*previous_fields.get(key, ()), *current_fields.get(key, ())))
        )

    return replace(
        previous,
        key=_pick(previous, current, "key"),
        title=_pick(previous, current, "title"),
        year=int(_pick(previous, current, "year")),
        venue=_pick(previous, current, "venue"),
        doi=_pick(previous, current, "doi"),
        official_url=_pick(previous, current, "official_url"),
        authors=_pick(previous, current, "authors"),
        abstract=_pick(previous, current, "abstract"),
        publication_type=_pick(previous, current, "publication_type"),
        track=_pick(previous, current, "track"),
        publication_date=_pick(previous, current, "publication_date"),
        relevance_score=max(previous.relevance_score, current.relevance_score),
        hard_gates_passed=previous.hard_gates_passed or current.hard_gates_passed,
        evidence_fields=tuple(
            dict.fromkeys((*previous.evidence_fields, *current.evidence_fields))
        ),
        keywords=tuple(dict.fromkeys((*previous.keywords, *current.keywords))),
        related_ids=tuple(dict.fromkeys((*previous.related_ids, *current.related_ids))),
        citation_count=max(previous.citation_count, current.citation_count),
        provenance=(current.provenance if _is_official(current) else previous.provenance),
        field_provenance=field_provenance,
        source_records=_merged_source_records(previous, current),
    )


class DiscoveryCoordinator:
    def __init__(
        self,
        providers: Iterable[DiscoveryProvider],
        *,
        enrichers: Iterable[DiscoveryEnricher] = (),
        progress: Callable[[str, Mapping[str, object]], None] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.providers = tuple(providers)
        self.enrichers = tuple(enrichers)
        self.progress = progress
        self._monotonic = monotonic

    def _report(self, event: str, **details: object) -> None:
        if self.progress is None:
            return
        safe: dict[str, object] = {}
        for name, value in details.items():
            if name == "provider":
                provider = str(value)
                safe[name] = (
                    provider if _SAFE_PROVIDER_ID.fullmatch(provider) else "unrecognized-provider"
                )
            elif name in {"candidates", "diagnostics", "coverage", "seconds"}:
                safe[name] = max(0, int(value)) if isinstance(value, (int, float, str)) else 0
            else:
                raise ValueError("unsupported discovery progress field")
        self.progress(event, safe)

    def discover(
        self,
        request: DiscoveryRequest,
        *,
        provider_timeout_seconds: float | None = None,
        partial_on_interrupt: bool = False,
        parallel_search: bool = False,
    ) -> DiscoveryBatch:
        """Run every applicable provider, then every enricher, and merge their candidates.

        ``provider_timeout_seconds`` bounds each provider and enricher; one that runs longer
        is recorded as a retryable ``provider_timeout`` diagnostic and discovery continues
        without its results. With ``partial_on_interrupt``, Ctrl+C or a job stop ends discovery
        with the candidates gathered so far (``interrupted`` is set) instead of raising. With
        ``parallel_search``, the keyword-search providers (different services) run at the
        same time after the venue listings; their results are merged in provider order, so
        the outcome does not depend on which finishes first.
        """
        bounded = provider_timeout_seconds is not None or partial_on_interrupt

        def call(function: Callable[[], Any]) -> Any:
            if not bounded:
                return function()
            return _call_bounded(function, provider_timeout_seconds, self._monotonic)

        interrupted = False
        seed_by_identity: dict[str, CandidateMetadata] = {
            candidate_identity(candidate): candidate
            for candidate in request.seed_candidates
        }
        merged = dict(seed_by_identity)
        diagnostics: list[DiscoveryDiagnostic] = []
        covered: list[str] = []
        coverage: list[CoverageSlice] = []
        configured = tuple(
            (provider, provider.capabilities()) for provider in self.providers
        )
        priority = {"official_index": 0, "venue_enumerator": 1}
        ordered = tuple(
            sorted(
                enumerate(configured),
                key=lambda item: (priority.get(item[1][1].source_class, 2), item[0]),
            )
        )
        def requested_name(coverage_venue: str) -> str | None:
            normalized = coverage_venue.casefold()
            for venue in request.venues:
                if normalized in {name.casefold() for name in venue.all_names}:
                    return venue.name
            return None

        official_provider_ids = {
            capability.provider_id
            for _, capability in configured
            if capability.source_class == "official_index"
        }
        official_complete: set[tuple[str, int]] = set()
        for item in request.seed_coverage:
            venue_name = requested_name(item.venue)
            if (
                item.provider_id in official_provider_ids
                and item.state == "complete"
                and venue_name is not None
            ):
                official_complete.add((venue_name, item.year))

        def requested_slices() -> set[tuple[str, int]]:
            return {
                (venue.name, year)
                for venue in request.venues
                for year in request.years
                if venue.supports_year(year)
            }

        def settle(capability, provider_request: DiscoveryRequest,
                   supported_venues: tuple[VenueScope, ...], outcome: tuple[str, Any],
                   elapsed: float) -> None:
            """Record one provider's outcome: a batch, a time-out, or a provider failure."""
            kind, value = outcome

            def failed_slices(error_code: str) -> None:
                if capability.source_class in _VENUE_SCOPED:
                    coverage.extend(
                        CoverageSlice(capability.provider_id, venue.name, year, "failed",
                                      diagnostic_code=error_code)
                        for venue in supported_venues
                        for year in provider_request.years
                        if venue.supports_year(year)
                    )

            if kind == "timeout":
                diagnostics.append(DiscoveryDiagnostic(
                    capability.provider_id, "discover", "provider_timeout",
                    f"provider did not finish within {provider_timeout_seconds:g} seconds; "
                    "its results are not included", retryable=True))
                failed_slices("provider_timeout")
                self._report("provider_timed_out", provider=capability.provider_id,
                             seconds=elapsed, diagnostics=1)
                return
            if kind == "error":
                if isinstance(value, (RateLimited, NetworkTransient)):
                    error_code, message, retryable = (
                        "network_transient", "provider temporarily unavailable", True)
                elif isinstance(value, (HttpStatusError, RuntimeError, ValueError)):
                    error_code, message, retryable = (
                        "provider_error", "provider failed during discovery", False)
                else:
                    raise value
                diagnostics.append(DiscoveryDiagnostic(
                    capability.provider_id, "discover", error_code, message,
                    retryable=retryable))
                failed_slices(error_code)
                self._report("provider_failed", provider=capability.provider_id,
                             diagnostics=1)
                return
            batch = value
            diagnostics.extend(batch.diagnostics)
            covered.extend(batch.covered_slices)
            coverage.extend(batch.coverage)
            if capability.source_class == "official_index":
                for item in batch.coverage:
                    venue_name = requested_name(item.venue)
                    if item.state == "complete" and venue_name is not None:
                        official_complete.add((venue_name, item.year))
            for candidate in batch.candidates:
                identity = candidate_identity(candidate)
                try:
                    merged[identity] = merge_candidates(merged.get(identity), candidate)
                except CandidateConflict:
                    diagnostics.append(
                        DiscoveryDiagnostic(
                            capability.provider_id,
                            "merge",
                            "identity_conflict",
                            "candidate identity fields conflict",
                        )
                    )
            self._report(
                "provider_completed",
                provider=capability.provider_id,
                candidates=len(batch.candidates),
                diagnostics=len(batch.diagnostics),
            )

        def stopped(capability, phase: str) -> None:
            diagnostics.append(DiscoveryDiagnostic(
                capability.provider_id, phase, "interrupted",
                "discovery was stopped before this provider finished", retryable=True))
            self._report("provider_interrupted", provider=capability.provider_id)

        # Keyword searches of different services, run side by side with parallel_search.
        deferred: list[tuple[DiscoveryProvider, Any, DiscoveryRequest,
                             tuple[VenueScope, ...]]] = []
        for _, (provider, capability) in ordered:
            if interrupted:
                break
            if not request.venues and capability.source_class in _VENUE_SCOPED:
                self._report("provider_skipped", provider=capability.provider_id)
                continue
            if (
                capability.source_class == "metadata_api"
                and request.venues
                and requested_slices()
                and requested_slices() <= official_complete
            ):
                # Keyword searches cannot add an in-scope paper that a complete official
                # listing lacks; they would only return papers from other venues.
                self._report("provider_skipped", provider=capability.provider_id)
                continue
            if capability.source_class == "venue_enumerator" and request.venues:
                supported_venues = tuple(
                    replace(
                        venue,
                        years=tuple(
                            year
                            for year in request.years
                            if venue.supports_year(year)
                            and capability.supports_year(year)
                            and (venue.name, year) not in official_complete
                        ),
                    )
                    for venue in request.venues
                    if capability.supports(venue)
                    and any(
                        venue.supports_year(year)
                        and capability.supports_year(year)
                        and (venue.name, year) not in official_complete
                        for year in request.years
                    )
                )
            else:
                supported_venues = tuple(
                    venue for venue in request.venues if capability.supports(venue)
                )
            if request.venues and not supported_venues:
                continue
            supported_years = tuple(
                year for year in request.years if capability.supports_year(year)
            )
            if request.years and not supported_years:
                continue
            provider_request = request.with_scope(
                supported_venues or request.venues,
                supported_years or request.years,
            )
            if parallel_search and capability.source_class == "metadata_api":
                deferred.append((provider, capability, provider_request, supported_venues))
                continue
            self._report("provider_started", provider=capability.provider_id)
            started = self._monotonic()
            outcome: tuple[str, Any]
            try:
                outcome = ("ok", call(lambda: provider.discover(provider_request)))
            except KeyboardInterrupt:
                if not partial_on_interrupt:
                    raise
                interrupted = True
                stopped(capability, "discover")
                break
            except ProviderTimeout:
                outcome = ("timeout", None)
            except (RateLimited, NetworkTransient, HttpStatusError, RuntimeError,
                    ValueError) as exc:
                outcome = ("error", exc)
            settle(capability, provider_request, supported_venues, outcome,
                   self._monotonic() - started)
        if deferred and not interrupted:
            for _, capability, _, _ in deferred:
                self._report("provider_started", provider=capability.provider_id)
            started = self._monotonic()
            outcomes, was_stopped = _run_side_by_side(
                [partial(provider.discover, provider_request)
                 for provider, _, provider_request, _ in deferred],
                provider_timeout_seconds, self._monotonic)
            if was_stopped and not partial_on_interrupt:
                raise KeyboardInterrupt
            for (_, capability, provider_request, supported_venues), result in zip(
                    deferred, outcomes, strict=True):
                if result is None:
                    stopped(capability, "discover")
                else:
                    settle(capability, provider_request, supported_venues, result,
                           self._monotonic() - started)
            interrupted = interrupted or was_stopped
        for enricher in self.enrichers:
            if interrupted:
                break
            capability = enricher.capabilities()
            self._report("enricher_started", provider=capability.provider_id)
            started = self._monotonic()
            snapshot = tuple(merged.values())
            try:
                batch = call(lambda: enricher.enrich(snapshot, request))
            except KeyboardInterrupt:
                if not partial_on_interrupt:
                    raise
                interrupted = True
                diagnostics.append(DiscoveryDiagnostic(
                    capability.provider_id, "enrich", "interrupted",
                    "discovery was stopped before metadata enrichment finished", retryable=True))
                self._report("enricher_interrupted", provider=capability.provider_id)
                break
            except ProviderTimeout:
                diagnostics.append(DiscoveryDiagnostic(
                    capability.provider_id, "enrich", "provider_timeout",
                    f"metadata enrichment did not finish within {provider_timeout_seconds:g} "
                    "seconds; abstracts it would have added are missing", retryable=True))
                self._report("enricher_timed_out", provider=capability.provider_id,
                             seconds=self._monotonic() - started, diagnostics=1)
                continue
            except (RateLimited, NetworkTransient):
                diagnostics.append(
                    DiscoveryDiagnostic(
                        capability.provider_id,
                        "enrich",
                        "network_transient",
                        "metadata enrichment is temporarily unavailable",
                        retryable=True,
                    )
                )
                self._report(
                    "enricher_failed",
                    provider=capability.provider_id,
                    diagnostics=1,
                )
                continue
            except (HttpStatusError, RuntimeError, ValueError):
                diagnostics.append(
                    DiscoveryDiagnostic(
                        capability.provider_id,
                        "enrich",
                        "provider_error",
                        "metadata enrichment failed",
                    )
                )
                self._report(
                    "enricher_failed",
                    provider=capability.provider_id,
                    diagnostics=1,
                )
                continue
            diagnostics.extend(batch.diagnostics)
            covered.extend(batch.covered_slices)
            coverage.extend(batch.coverage)
            for candidate in batch.candidates:
                identity = candidate_identity(candidate)
                try:
                    merged[identity] = merge_candidates(merged.get(identity), candidate)
                except CandidateConflict:
                    diagnostics.append(
                        DiscoveryDiagnostic(
                            capability.provider_id,
                            "merge",
                            "identity_conflict",
                            "candidate identity fields conflict",
                        )
                    )
            self._report(
                "enricher_completed",
                provider=capability.provider_id,
                candidates=len(batch.candidates),
                diagnostics=len(batch.diagnostics),
            )
        self._report(
            "discovery_completed",
            candidates=len(merged),
            diagnostics=len(diagnostics),
            coverage=len(coverage),
        )
        return DiscoveryBatch(
            candidates=tuple(
                candidate
                for identity, candidate in merged.items()
                if seed_by_identity.get(identity) != candidate
            ),
            diagnostics=tuple(diagnostics),
            covered_slices=tuple(dict.fromkeys(covered)),
            coverage=tuple(coverage),
            interrupted=interrupted,
        )
