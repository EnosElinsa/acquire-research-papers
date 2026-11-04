from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace

from acquire_research_papers.discovery.contracts import (
    CandidateMetadata,
    CandidatePage,
    CoverageSlice,
    DiscoveryBatch,
    DiscoveryCapabilities,
    DiscoveryDiagnostic,
    DiscoveryRequest,
    VenueScope,
)
from acquire_research_papers.http import HttpStatusError, NetworkTransient, RateLimited
from acquire_research_papers.models import normalize_doi


def crossref_scope(venue: VenueScope) -> dict:
    """Describe the same identifier gate used by live venue enumeration."""
    available = not ("conference" in venue.kind.casefold() and not venue.collection_doi and not venue.issn)
    return {
        "available": available,
        "identifier": "issn" if venue.issn else "collection_doi" if venue.collection_doi else "container_title",
        "diagnostic": None if available else "exact_identifier_required",
    }


@dataclass(frozen=True)
class CrossrefVenueDiscoveryProvider:
    searcher: Callable[..., CandidatePage]
    provider_id: str = "crossref"
    page_size: int = 1000

    def capabilities(self) -> DiscoveryCapabilities:
        return DiscoveryCapabilities(
            provider_id=self.provider_id,
            source_class="venue_enumerator",
            evidence_fields=frozenset(
                {
                    "title",
                    "abstract",
                    "authors",
                    "keywords",
                    "venue",
                    "publication_type",
                    "publication_date",
                }
            ),
        )

    def _diagnostic(
        self,
        *,
        error_code: str,
        message: str,
        venue: str,
        year: int,
        retryable: bool = False,
    ) -> DiscoveryDiagnostic:
        return DiscoveryDiagnostic(
            provider_id=self.provider_id,
            phase="venue-enumeration",
            error_code=error_code,
            message=message,
            venue=venue,
            year=year,
            retryable=retryable,
        )

    def discover(self, request: DiscoveryRequest) -> DiscoveryBatch:
        candidates: list[CandidateMetadata] = []
        diagnostics: list[DiscoveryDiagnostic] = []
        coverage: list[CoverageSlice] = []
        page_size = max(1, min(self.page_size, 1000))
        for venue in request.venues:
            for year in request.years:
                if not venue.supports_year(year):
                    continue
                slice_label = f"{self.provider_id}:{venue.name}:{year}"
                if slice_label in request.completed_slices:
                    continue
                if not crossref_scope(venue)["available"]:
                    if venue.openalex_source:
                        # The declared OpenAlex source enumerates this venue instead.
                        continue
                    diagnostics.append(
                        self._diagnostic(
                            error_code="exact_identifier_required",
                            message=(
                                "Crossref conference enumeration requires an exact "
                                "collection DOI"
                            ),
                            venue=venue.name,
                            year=year,
                        )
                    )
                    coverage.append(
                        CoverageSlice(
                            provider_id=self.provider_id,
                            venue=venue.name,
                            year=year,
                            state="failed",
                            diagnostic_code="exact_identifier_required",
                        )
                    )
                    continue
                collection_dois: tuple[str | None, ...] = venue.collection_doi or (None,)
                completed_enumerations = 0
                pages_fetched = 0
                records_fetched = 0
                first_error = ""
                resume_cursor: str | None = None
                for collection_doi in collection_dois:
                    filters: dict[str, str | tuple[str, ...]] = {
                        "from-pub-date": f"{year:04d}-01-01",
                        "until-pub-date": f"{year:04d}-12-31",
                    }
                    query = venue.name
                    if venue.issn:
                        # All ISSNs in one request: Crossref ORs them, so print and online
                        # ISSNs, or the ISSNs before and after a rename, yield each work once.
                        filters["issn"] = tuple(venue.issn)
                        query = ""
                    elif collection_doi:
                        filters["alternative-id"] = collection_doi
                        query = ""
                    else:
                        filters["container-title"] = venue.name
                        query = ""
                    cursor = "*"
                    seen_pages: set[
                        tuple[tuple[str, str, str, int, str], ...]
                    ] = set()
                    enumeration_records = 0
                    while True:
                        try:
                            page = self.searcher(
                                query,
                                rows=page_size,
                                cursor=cursor,
                                filters=filters,
                                query_field="container-title",
                            )
                        except (RateLimited, NetworkTransient):
                            first_error = first_error or "network_transient"
                            resume_cursor = resume_cursor or cursor
                            diagnostics.append(
                                self._diagnostic(
                                    error_code="network_transient",
                                    message=(
                                        "Crossref venue enumeration is temporarily "
                                        "unavailable"
                                    ),
                                    venue=venue.name,
                                    year=year,
                                    retryable=True,
                                )
                            )
                            break
                        except (HttpStatusError, RuntimeError, ValueError):
                            first_error = first_error or "provider_error"
                            resume_cursor = resume_cursor or cursor
                            diagnostics.append(
                                self._diagnostic(
                                    error_code="provider_error",
                                    message="Crossref venue enumeration failed",
                                    venue=venue.name,
                                    year=year,
                                )
                            )
                            break

                        pages_fetched += 1
                        if not page.candidates:
                            completed_enumerations += 1
                            break
                        page_candidates = page.candidates
                        if venue.issn or collection_doi or filters.get("container-title"):
                            page_candidates = tuple(
                                replace(
                                    candidate,
                                    venue=venue.name,
                                    provenance={
                                        **candidate.provenance,
                                        "reported_venue": candidate.venue,
                                    },
                                )
                                for candidate in page.candidates
                            )
                        page_identity = tuple(
                            (
                                normalize_doi(candidate.doi) if candidate.doi else "",
                                candidate.key,
                                candidate.title,
                                candidate.year,
                                candidate.venue,
                            )
                            for candidate in page_candidates
                        )
                        if page_identity in seen_pages:
                            first_error = first_error or "repeated_page"
                            resume_cursor = resume_cursor or page.next_cursor
                            diagnostics.append(
                                self._diagnostic(
                                    error_code="repeated_page",
                                    message="Crossref returned a repeated result page",
                                    venue=venue.name,
                                    year=year,
                                )
                            )
                            break
                        seen_pages.add(page_identity)
                        page_records = len(page_candidates)
                        enumeration_records += page_records
                        records_fetched += page_records
                        candidates.extend(page_candidates)
                        if (
                            page.total_results is not None
                            and enumeration_records >= page.total_results
                        ) or not page.next_cursor:
                            completed_enumerations += 1
                            break
                        cursor = page.next_cursor
                if completed_enumerations == len(collection_dois):
                    state = "complete"
                elif pages_fetched or records_fetched or completed_enumerations:
                    state = "partial"
                else:
                    state = "failed"
                coverage.append(
                    CoverageSlice(
                        provider_id=self.provider_id,
                        venue=venue.name,
                        year=year,
                        state=state,
                        pages_fetched=pages_fetched,
                        records_fetched=records_fetched,
                        next_cursor=resume_cursor,
                        diagnostic_code=first_error,
                        records_recognized=records_fetched,
                    )
                )
        return DiscoveryBatch(
            candidates=tuple(candidates),
            diagnostics=tuple(diagnostics),
            coverage=tuple(coverage),
        )


@dataclass(frozen=True)
class OpenAlexVenueDiscoveryProvider:
    """Enumerate a venue/year through the exact OpenAlex source IDs declared on the venue.

    Used where Crossref has no exact identifier, notably IEEE conference series such as INFOCOM,
    ICC, and GLOBECOM, whose OpenAlex records carry DOIs and abstracts. "complete" means the
    OpenAlex enumeration finished; OpenAlex can lag behind a recent edition. With a ``counter``,
    a finished slice holding under ``lag_ratio`` of the previous year's works (when that year
    has at least ``lag_minimum``) also gets a non-retryable ``possible_upstream_lag`` warning.
    """

    searcher: Callable[..., CandidatePage]
    configured: bool = True
    provider_id: str = "openalex-venue"
    page_size: int = 200
    max_pages: int = 100
    counter: Callable[[str, int], int] | None = None
    lag_ratio: float = 0.5
    lag_minimum: int = 50

    def capabilities(self) -> DiscoveryCapabilities:
        return DiscoveryCapabilities(
            provider_id=self.provider_id,
            source_class="venue_enumerator",
            evidence_fields=frozenset({"title", "abstract", "authors", "venue",
                                       "publication_type", "publication_date"}),
            requires_credentials=not self.configured,
        )

    def _diagnostic(self, error_code: str, message: str, venue: str, year: int,
                    *, retryable: bool = False) -> DiscoveryDiagnostic:
        return DiscoveryDiagnostic(provider_id=self.provider_id, phase="venue-enumeration",
                                   error_code=error_code, message=message, venue=venue,
                                   year=year, retryable=retryable)

    def discover(self, request: DiscoveryRequest) -> DiscoveryBatch:
        candidates: list[CandidateMetadata] = []
        diagnostics: list[DiscoveryDiagnostic] = []
        coverage: list[CoverageSlice] = []
        for venue in request.venues:
            if not venue.openalex_source:
                continue
            for year in request.years:
                if not venue.supports_year(year):
                    continue
                if f"{self.provider_id}:{venue.name}:{year}" in request.completed_slices:
                    continue
                if not self.configured:
                    diagnostics.append(self._diagnostic(
                        "configuration_required",
                        "openalex_source venues need an OpenAlex API key (arp config setup openalex)",
                        venue.name, year))
                    coverage.append(CoverageSlice(self.provider_id, venue.name, year, "failed",
                                                  diagnostic_code="configuration_required"))
                    continue
                pages = records = finished = 0
                error = ""
                for source_id in venue.openalex_source:
                    cursor: str | None = "*"
                    fetched = 0
                    for _ in range(self.max_pages):
                        try:
                            page = self.searcher(source_id, year, cursor=cursor,
                                                 per_page=self.page_size)
                        except (RateLimited, NetworkTransient):
                            error = error or "network_transient"
                            diagnostics.append(self._diagnostic(
                                "network_transient", "OpenAlex venue enumeration is temporarily "
                                "unavailable", venue.name, year, retryable=True))
                            break
                        except (HttpStatusError, RuntimeError, ValueError):
                            error = error or "provider_error"
                            diagnostics.append(self._diagnostic(
                                "provider_error", "OpenAlex venue enumeration failed",
                                venue.name, year))
                            break
                        pages += 1
                        page_candidates = tuple(
                            replace(candidate, venue=venue.name, provenance={
                                **candidate.provenance, "reported_venue": candidate.venue})
                            for candidate in page.candidates
                        )
                        candidates.extend(page_candidates)
                        fetched += len(page_candidates)
                        if (not page_candidates or not page.next_cursor
                                or (page.total_results is not None
                                    and fetched >= page.total_results)):
                            finished += 1
                            break
                        cursor = page.next_cursor
                    else:
                        error = error or "page_limit"
                        diagnostics.append(self._diagnostic(
                            "page_limit", "OpenAlex venue enumeration reached its page limit",
                            venue.name, year))
                    records += fetched
                state = ("complete" if finished == len(venue.openalex_source)
                         else "partial" if pages else "failed")
                coverage.append(CoverageSlice(self.provider_id, venue.name, year, state,
                                              pages_fetched=pages, records_fetched=records,
                                              diagnostic_code=error, records_recognized=records))
                if state == "complete" and (warning := self._lag_warning(venue, year, records)):
                    diagnostics.append(warning)
        return DiscoveryBatch(candidates=tuple(candidates), diagnostics=tuple(diagnostics),
                              coverage=tuple(coverage))

    def _lag_warning(self, venue: VenueScope, year: int, count: int) -> DiscoveryDiagnostic | None:
        """Flag an edition that is much smaller than the one before; the slice stays complete."""
        if self.counter is None:
            return None
        try:
            previous = sum(self.counter(source_id, year - 1) for source_id in venue.openalex_source)
        except (RateLimited, NetworkTransient, HttpStatusError, RuntimeError, ValueError):
            return None  # best effort: without the previous count there is nothing to compare
        if previous < self.lag_minimum or count >= previous * self.lag_ratio:
            return None
        return self._diagnostic(
            "possible_upstream_lag",
            f"OpenAlex lists {count} works for {venue.name} {year} against {previous} for "
            f"{year - 1}; OpenAlex may not have indexed the {year} edition fully yet",
            venue.name, year)


def _normalized(value: str) -> str:
    return " ".join(re.findall(r"\w+", value.casefold()))


@dataclass(frozen=True)
class DoiBatchEnrichmentProvider:
    provider_id: str
    lookup: Callable[[list[str]], Iterable[CandidateMetadata]]
    batch_size: int = 500
    pause_seconds: float = 0.0
    sleeper: Callable[[float], None] = time.sleep

    def capabilities(self) -> DiscoveryCapabilities:
        return DiscoveryCapabilities(
            provider_id=self.provider_id,
            source_class="metadata_enricher",
            evidence_fields=frozenset(
                {
                    "title",
                    "abstract",
                    "authors",
                    "venue",
                    "publication_type",
                    "publication_date",
                }
            ),
        )

    def enrich(
        self,
        candidates: tuple[CandidateMetadata, ...],
        request: DiscoveryRequest,
    ) -> DiscoveryBatch:
        coverage_label = f"{self.provider_id}:doi-batch"
        if coverage_label in request.completed_slices:
            return DiscoveryBatch()
        venue_names = {
            _normalized(name)
            for venue in request.venues
            for name in venue.all_names
        }
        years = set(request.years)
        dois = list(
            dict.fromkeys(
                normalize_doi(candidate.doi)
                for candidate in candidates
                if candidate.doi
                and not candidate.abstract.strip()
                and (not years or candidate.year in years)
                and (not venue_names or _normalized(candidate.venue) in venue_names)
            )
        )
        if not dois:
            return DiscoveryBatch(covered_slices=(coverage_label,))
        found: list[CandidateMetadata] = []
        diagnostics: list[DiscoveryDiagnostic] = []
        successful_chunks = 0
        chunk_size = max(1, min(self.batch_size, 500))
        for index in range(0, len(dois), chunk_size):
            chunk = dois[index : index + chunk_size]
            try:
                found.extend(self.lookup(chunk))
            except RateLimited:
                diagnostics.append(
                    DiscoveryDiagnostic(
                        provider_id=self.provider_id,
                        phase="doi-enrichment",
                        error_code="rate_limited",
                        message="DOI metadata enrichment was rate limited",
                        retryable=True,
                    )
                )
                break
            except NetworkTransient:
                diagnostics.append(
                    DiscoveryDiagnostic(
                        provider_id=self.provider_id,
                        phase="doi-enrichment",
                        error_code="network_transient",
                        message="DOI metadata enrichment is temporarily unavailable",
                        retryable=True,
                    )
                )
                continue
            except (HttpStatusError, RuntimeError, ValueError):
                diagnostics.append(
                    DiscoveryDiagnostic(
                        provider_id=self.provider_id,
                        phase="doi-enrichment",
                        error_code="provider_error",
                        message="DOI metadata enrichment failed",
                    )
                )
                continue
            successful_chunks += 1
            if index + chunk_size < len(dois) and self.pause_seconds > 0:
                self.sleeper(self.pause_seconds)
        return DiscoveryBatch(
            candidates=tuple(found),
            diagnostics=tuple(diagnostics),
            covered_slices=(
                (f"{self.provider_id}:doi-batch",)
                if successful_chunks and not diagnostics
                else ()
            ),
        )


@dataclass(frozen=True)
class QueryApiProvider:
    provider_id: str
    searcher: Callable[[str, int], Iterable[CandidateMetadata]]
    configured: bool = True

    def capabilities(self) -> DiscoveryCapabilities:
        return DiscoveryCapabilities(
            provider_id=self.provider_id,
            source_class="metadata_api",
            requires_credentials=not self.configured,
        )

    def discover(self, request: DiscoveryRequest) -> DiscoveryBatch:
        if not self.configured:
            return DiscoveryBatch()
        if self.provider_id in request.completed_slices:
            return DiscoveryBatch()
        found: list[CandidateMetadata] = []
        diagnostics: list[DiscoveryDiagnostic] = []
        successful_query = False
        for query in request.queries:
            try:
                found.extend(self.searcher(query, request.maximum))
            except (RateLimited, NetworkTransient):
                diagnostics.append(
                    DiscoveryDiagnostic(
                        provider_id=self.provider_id,
                        phase="query",
                        error_code="network_transient",
                        message="metadata query is temporarily unavailable",
                        retryable=True,
                    )
                )
                continue
            except (HttpStatusError, RuntimeError, ValueError):
                diagnostics.append(
                    DiscoveryDiagnostic(
                        provider_id=self.provider_id,
                        phase="query",
                        error_code="provider_error",
                        message="metadata query failed",
                    )
                )
                continue
            successful_query = True
        return DiscoveryBatch(
            candidates=tuple(found),
            diagnostics=tuple(diagnostics),
            covered_slices=(self.provider_id,) if successful_query else (),
        )
