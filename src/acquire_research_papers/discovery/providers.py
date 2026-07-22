from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

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
                filters = {
                    "from-pub-date": f"{year:04d}-01-01",
                    "until-pub-date": f"{year:04d}-12-31",
                }
                query = venue.name
                if venue.issn:
                    filters["issn"] = venue.issn[0]
                    query = ""
                cursor = "*"
                seen_cursors = {cursor}
                pages_fetched = 0
                records_fetched = 0
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
                        state = "partial" if pages_fetched else "failed"
                        diagnostics.append(
                            self._diagnostic(
                                error_code="network_transient",
                                message="Crossref venue enumeration is temporarily unavailable",
                                venue=venue.name,
                                year=year,
                                retryable=True,
                            )
                        )
                        coverage.append(
                            CoverageSlice(
                                provider_id=self.provider_id,
                                venue=venue.name,
                                year=year,
                                state=state,
                                pages_fetched=pages_fetched,
                                records_fetched=records_fetched,
                                next_cursor=cursor,
                                diagnostic_code="network_transient",
                            )
                        )
                        break
                    except (HttpStatusError, RuntimeError, ValueError):
                        state = "partial" if pages_fetched else "failed"
                        diagnostics.append(
                            self._diagnostic(
                                error_code="provider_error",
                                message="Crossref venue enumeration failed",
                                venue=venue.name,
                                year=year,
                            )
                        )
                        coverage.append(
                            CoverageSlice(
                                provider_id=self.provider_id,
                                venue=venue.name,
                                year=year,
                                state=state,
                                pages_fetched=pages_fetched,
                                records_fetched=records_fetched,
                                next_cursor=cursor,
                                diagnostic_code="provider_error",
                            )
                        )
                        break

                    pages_fetched += 1
                    records_fetched += len(page.candidates)
                    candidates.extend(page.candidates)
                    if not page.candidates or not page.next_cursor:
                        coverage.append(
                            CoverageSlice(
                                provider_id=self.provider_id,
                                venue=venue.name,
                                year=year,
                                state="complete",
                                pages_fetched=pages_fetched,
                                records_fetched=records_fetched,
                            )
                        )
                        break
                    if page.next_cursor in seen_cursors:
                        diagnostics.append(
                            self._diagnostic(
                                error_code="cursor_cycle",
                                message="Crossref returned a repeated pagination cursor",
                                venue=venue.name,
                                year=year,
                            )
                        )
                        coverage.append(
                            CoverageSlice(
                                provider_id=self.provider_id,
                                venue=venue.name,
                                year=year,
                                state="partial",
                                pages_fetched=pages_fetched,
                                records_fetched=records_fetched,
                                next_cursor=page.next_cursor,
                                diagnostic_code="cursor_cycle",
                            )
                        )
                        break
                    cursor = page.next_cursor
                    seen_cursors.add(cursor)
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
        successful = False
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
            successful = True
        return DiscoveryBatch(
            candidates=tuple(found),
            diagnostics=tuple(diagnostics),
            covered_slices=(f"{self.provider_id}:doi-batch",) if successful else (),
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
