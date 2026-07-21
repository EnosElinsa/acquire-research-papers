from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from acquire_research_papers.discovery.contracts import (
    CandidateMetadata,
    DiscoveryBatch,
    DiscoveryCapabilities,
    DiscoveryRequest,
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
        for query in request.queries:
            found.extend(self.searcher(query, request.maximum))
        return DiscoveryBatch(
            candidates=tuple(found),
            covered_slices=(self.provider_id,),
        )

