from acquire_research_papers.discovery.contracts import DiscoveryRequest


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

