from __future__ import annotations

from dataclasses import dataclass

from acquire_research_papers.discovery.contracts import (
    CandidateMetadata,
    DiscoveryBatch,
    DiscoveryCapabilities,
    DiscoveryRequest,
)
from acquire_research_papers.discovery.coordinator import DiscoveryCoordinator
from acquire_research_papers.discovery.providers import QueryApiProvider


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


def test_query_api_provider_runs_each_query_with_the_requested_limit() -> None:
    calls: list[tuple[str, int]] = []

    def searcher(query: str, rows: int):
        calls.append((query, rows))
        return ()

    provider = QueryApiProvider("api", searcher)

    batch = provider.discover(request())

    assert calls == [("evolution", 5)]
    assert batch.covered_slices == ("api",)

