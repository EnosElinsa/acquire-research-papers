from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from acquire_research_papers.discovery.contracts import (
    CandidateMetadata,
    DiscoveryBatch,
    DiscoveryCapabilities,
    DiscoveryDiagnostic,
    DiscoveryRequest,
)
from acquire_research_papers.http import HttpStatusError, NetworkTransient, RateLimited
from acquire_research_papers.models import normalize_doi


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
