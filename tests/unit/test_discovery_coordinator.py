from __future__ import annotations

from dataclasses import dataclass

from acquire_research_papers.discovery.contracts import (
    CandidateMetadata,
    DiscoveryBatch,
    DiscoveryCapabilities,
    DiscoveryRequest,
)
from acquire_research_papers.discovery.coordinator import DiscoveryCoordinator
from acquire_research_papers.discovery.providers import (
    DoiBatchEnrichmentProvider,
    QueryApiProvider,
)
from acquire_research_papers.http import RateLimited


@dataclass
class FakeProvider:
    provider_id: str
    batch: DiscoveryBatch
    venue_aliases: frozenset[str] = frozenset()
    supported_years: frozenset[int] = frozenset()
    received: DiscoveryRequest | None = None

    def capabilities(self) -> DiscoveryCapabilities:
        return DiscoveryCapabilities(
            provider_id=self.provider_id,
            source_class="official_index",
            venue_aliases=self.venue_aliases,
            supported_years=self.supported_years,
        )

    def discover(self, request: DiscoveryRequest) -> DiscoveryBatch:
        self.received = request
        return self.batch


def request() -> DiscoveryRequest:
    return DiscoveryRequest.from_spec(
        {
            "name": "test corpus",
            "target": {"minimum": 1, "preferred": 1, "maximum": 5},
            "scope": {
                "venues": [
                    {"name": "Venue A", "aliases": ["VA"]},
                    {"name": "Venue B", "aliases": ["VB"]},
                ],
                "years": {"include": [2026, 2025], "priority": [2026, 2025]},
                "topics": {"include": ["evolution"]},
            },
        }
    )


def test_coordinator_merges_official_abstract_into_api_identity() -> None:
    api = CandidateMetadata(
        "api",
        "Same Paper",
        2026,
        "Venue A",
        0.8,
        True,
        ("title",),
        doi="10.1000/same",
        provenance={"source": "crossref"},
    )
    official = CandidateMetadata(
        "official",
        "Same Paper",
        2026,
        "Venue A",
        0.9,
        True,
        ("title", "abstract"),
        doi="10.1000/same",
        abstract="Official abstract",
        official_url="https://venue.example/paper",
        provenance={"source": "official-index"},
    )
    coordinator = DiscoveryCoordinator(
        [
            FakeProvider("api", DiscoveryBatch((api,))),
            FakeProvider("official", DiscoveryBatch((official,))),
        ]
    )

    batch = coordinator.discover(request())

    assert len(batch.candidates) == 1
    candidate = batch.candidates[0]
    assert candidate.abstract == "Official abstract"
    assert candidate.official_url == "https://venue.example/paper"
    assert set(candidate.evidence_fields) == {"title", "abstract"}
    assert {record["source"] for record in candidate.source_records} == {
        "crossref",
        "official-index",
    }


def test_coordinator_records_one_provider_failure_and_continues() -> None:
    class BrokenProvider(FakeProvider):
        def discover(self, request: DiscoveryRequest) -> DiscoveryBatch:
            raise RuntimeError("page body with secret must not be copied")

    good = CandidateMetadata("good", "Good", 2026, "Venue A", 0.9, True, ("title",))
    coordinator = DiscoveryCoordinator(
        [
            BrokenProvider("broken", DiscoveryBatch()),
            FakeProvider("good", DiscoveryBatch((good,))),
        ]
    )

    batch = coordinator.discover(request())

    assert [item.key for item in batch.candidates] == ["good"]
    assert batch.diagnostics[0].provider_id == "broken"
    assert batch.diagnostics[0].message == "provider failed during discovery"
    assert "secret" not in batch.diagnostics[0].message


def test_coordinator_slices_provider_by_capability() -> None:
    provider = FakeProvider(
        "venue-b",
        DiscoveryBatch(covered_slices=("venue-b:2025",)),
        venue_aliases=frozenset({"VB"}),
        supported_years=frozenset({2025}),
    )

    batch = DiscoveryCoordinator([provider]).discover(request())

    assert batch.covered_slices == ("venue-b:2025",)
    assert provider.received is not None
    assert [venue.name for venue in provider.received.venues] == ["Venue B"]
    assert provider.received.years == (2025,)
    assert provider.received.year_priority == (2025,)


def test_coordinator_reports_identity_conflict_without_overwriting() -> None:
    first = CandidateMetadata(
        "one",
        "Paper",
        2026,
        "Venue A",
        0.9,
        True,
        ("title",),
        official_url="https://venue.example/paper",
    )
    conflict = CandidateMetadata(
        "two",
        "Paper",
        2025,
        "Venue A",
        0.95,
        True,
        ("title",),
        official_url="https://venue.example/paper",
    )

    batch = DiscoveryCoordinator(
        [
            FakeProvider("first", DiscoveryBatch((first,))),
            FakeProvider("second", DiscoveryBatch((conflict,))),
        ]
    ).discover(request())

    assert len(batch.candidates) == 1
    assert batch.candidates[0].year == 2026
    assert [item.error_code for item in batch.diagnostics] == ["identity_conflict"]


def test_coordinator_keeps_primary_year_when_same_doi_metadata_differs() -> None:
    crossref = CandidateMetadata(
        "crossref",
        "Same DOI Paper",
        2025,
        "Venue A",
        0.8,
        True,
        ("title", "venue"),
        doi="10.1000/same-doi",
        provenance={"source": "crossref"},
    )
    semantic = CandidateMetadata(
        "semantic",
        "Same DOI Paper",
        2024,
        "Venue A",
        0.5,
        True,
        ("title", "abstract", "venue"),
        doi="10.1000/same-doi",
        abstract="Useful abstract evidence",
        provenance={"source": "semantic-scholar"},
    )

    batch = DiscoveryCoordinator(
        [
            FakeProvider("crossref", DiscoveryBatch((crossref,))),
            FakeProvider("semantic", DiscoveryBatch((semantic,))),
        ]
    ).discover(request())

    assert len(batch.candidates) == 1
    assert batch.candidates[0].year == 2025
    assert batch.candidates[0].abstract == "Useful abstract evidence"
    assert batch.diagnostics == ()


def test_query_api_provider_runs_each_query_with_the_requested_limit() -> None:
    calls: list[tuple[str, int]] = []

    def searcher(query: str, rows: int):
        calls.append((query, rows))
        return ()

    provider = QueryApiProvider("api", searcher)

    batch = provider.discover(request())

    assert calls == [("evolution", 5)]
    assert batch.covered_slices == ("api",)


def test_query_api_provider_preserves_successful_queries_after_rate_limit() -> None:
    found = CandidateMetadata(
        "found",
        "Found Paper",
        2026,
        "Venue A",
        0.9,
        True,
        ("title", "abstract"),
    )

    def searcher(query: str, rows: int):
        if query == "second":
            raise RateLimited(429, "https://metadata.example/search")
        return (found,)

    provider_request = DiscoveryRequest.from_spec(
        {
            "name": "partial metadata",
            "target": {"minimum": 1, "maximum": 5},
            "scope": {"topics": {"include": ["first", "second"]}},
        }
    )

    batch = QueryApiProvider("api", searcher).discover(provider_request)

    assert batch.candidates == (found,)
    assert batch.covered_slices == ("api",)
    assert len(batch.diagnostics) == 1
    assert batch.diagnostics[0].error_code == "network_transient"
    assert batch.diagnostics[0].retryable


def test_coordinator_enriches_in_scope_dois_after_provider_discovery() -> None:
    seeds = (
        CandidateMetadata(
            "crossref-a",
            "In Scope",
            2026,
            "Venue A",
            0.8,
            True,
            ("title", "venue"),
            doi="10.1000/in-scope",
            provenance={"source": "crossref"},
        ),
        CandidateMetadata(
            "crossref-b",
            "Out of Scope",
            2026,
            "Other Venue",
            0.8,
            True,
            ("title", "venue"),
            doi="10.1000/out-of-scope",
            provenance={"source": "crossref"},
        ),
    )
    looked_up: list[str] = []

    def lookup(dois: list[str]):
        looked_up.extend(dois)
        return (
            CandidateMetadata(
                "s2-a",
                "In Scope",
                2026,
                "Venue A",
                0.5,
                True,
                ("title", "abstract", "venue"),
                doi="10.1000/in-scope",
                abstract="Enriched abstract",
                provenance={"source": "semantic-scholar"},
            ),
        )

    batch = DiscoveryCoordinator(
        [FakeProvider("crossref", DiscoveryBatch(seeds))],
        enrichers=[DoiBatchEnrichmentProvider("semantic-scholar", lookup)],
    ).discover(request())

    assert looked_up == ["10.1000/in-scope"]
    enriched = next(item for item in batch.candidates if item.doi == "10.1000/in-scope")
    assert enriched.abstract == "Enriched abstract"
    assert enriched.official_url is None
    assert batch.covered_slices == ("semantic-scholar:doi-batch",)
