from __future__ import annotations

import re
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
)
from acquire_research_papers.http import HttpStatusError, NetworkTransient, RateLimited
from acquire_research_papers.models import normalize_doi


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
                if (
                    "conference" in venue.kind.casefold()
                    and not venue.collection_doi
                    and not venue.issn
                ):
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
                    filters = {
                        "from-pub-date": f"{year:04d}-01-01",
                        "until-pub-date": f"{year:04d}-12-31",
                    }
                    query = venue.name
                    if venue.issn:
                        filters["issn"] = venue.issn[0]
                        query = ""
                    elif collection_doi:
                        filters["alternative-id"] = collection_doi
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
                        if venue.issn or collection_doi:
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
                    )
                )
        return DiscoveryBatch(
            candidates=tuple(candidates),
            diagnostics=tuple(diagnostics),
            coverage=tuple(coverage),
        )


def _normalized(value: str) -> str:
    return " ".join(re.findall(r"\w+", value.casefold()))


@dataclass(frozen=True)
class DoiBatchEnrichmentProvider:
    provider_id: str
    lookup: Callable[[list[str]], Iterable[CandidateMetadata]]
    batch_size: int = 500

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
                and (not years or candidate.year in years)
                and (not venue_names or _normalized(candidate.venue) in venue_names)
            )
        )
        found: list[CandidateMetadata] = []
        diagnostics: list[DiscoveryDiagnostic] = []
        successful_chunks = 0
        for index in range(0, len(dois), max(1, min(self.batch_size, 500))):
            chunk = dois[index : index + self.batch_size]
            try:
                found.extend(self.lookup(chunk))
            except (RateLimited, NetworkTransient):
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
