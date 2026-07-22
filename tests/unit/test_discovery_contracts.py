from acquire_research_papers.discovery.contracts import (
    CoverageSlice,
    DiscoveryBatch,
    DiscoveryRequest,
)


def test_discovery_request_preserves_generic_venue_scope() -> None:
    request = DiscoveryRequest.from_spec(
        {
            "name": "generic corpus",
            "target": {"minimum": 1, "preferred": 2, "maximum": 3},
            "scope": {
                "venues": [
                    {
                        "name": "Invented Proceedings",
                        "aliases": ["IP"],
                        "years": [2026],
                        "kind": "conference",
                        "short_name": "IP",
                        "publisher": "Invented Society",
                    }
                ],
                "years": {"include": [2026], "priority": [2026]},
                "publication_types": {"include": ["full"]},
                "topics": {"include": ["evolution"], "synonyms": ["genetic"]},
            },
        }
    )

    assert request.venues[0].all_names == ("Invented Proceedings", "IP")
    assert request.venues[0].short_name == "IP"
    assert request.venues[0].publisher == "Invented Society"
    assert request.venues[0].years == (2026,)
    assert request.venues[0].supports_year(2026)
    assert not request.venues[0].supports_year(2025)
    assert request.queries == ("evolution", "genetic")
    assert request.maximum == 3


def test_discovery_request_can_be_sliced_without_changing_the_original() -> None:
    request = DiscoveryRequest.from_spec(
        {
            "name": "generic corpus",
            "target": {"minimum": 1, "preferred": 1, "maximum": 2},
            "scope": {
                "venues": [
                    {"name": "Venue A"},
                    {"name": "Venue B"},
                ],
                "years": {"include": [2026, 2025], "priority": [2026, 2025]},
            },
        }
    )

    sliced = request.with_scope((request.venues[1],), (2025,))

    assert [venue.name for venue in sliced.venues] == ["Venue B"]
    assert sliced.years == (2025,)
    assert sliced.year_priority == (2025,)
    assert [venue.name for venue in request.venues] == ["Venue A", "Venue B"]


def test_coverage_slice_serializes_checkpoint_state() -> None:
    coverage = CoverageSlice(
        provider_id="crossref",
        venue="IEEE Transactions on Cybernetics",
        year=2025,
        state="partial",
        pages_fetched=3,
        records_fetched=247,
        next_cursor="cursor-4",
        diagnostic_code="network_transient",
    )

    assert coverage.to_dict() == {
        "provider_id": "crossref",
        "venue": "IEEE Transactions on Cybernetics",
        "year": 2025,
        "state": "partial",
        "pages_fetched": 3,
        "records_fetched": 247,
        "next_cursor": "cursor-4",
        "diagnostic_code": "network_transient",
    }
    assert coverage.label == "crossref:IEEE Transactions on Cybernetics:2025"


def test_discovery_batch_preserves_legacy_and_structured_coverage() -> None:
    complete = CoverageSlice(
        provider_id="crossref",
        venue="Venue A",
        year=2026,
        state="complete",
        pages_fetched=2,
        records_fetched=11,
    )
    partial = CoverageSlice(
        provider_id="crossref",
        venue="Venue B",
        year=2026,
        state="partial",
        pages_fetched=1,
        records_fetched=4,
        next_cursor="next",
    )

    batch = DiscoveryBatch(
        covered_slices=("legacy:2025",),
        coverage=(complete, partial),
    )

    assert batch.complete_slice_labels == (
        "legacy:2025",
        "crossref:Venue A:2026",
    )
