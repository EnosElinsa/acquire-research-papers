from __future__ import annotations

from pathlib import Path

from acquire_research_papers.discovery.contracts import DiscoveryRequest
from acquire_research_papers.discovery.official.acl import AclAnthologyDiscoveryProvider


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "discovery" / "acl"


def request() -> DiscoveryRequest:
    return DiscoveryRequest.from_spec(
        {
            "name": "acl",
            "target": {"minimum": 1, "preferred": 1, "maximum": 10},
            "scope": {
                "venues": [
                    {
                        "name": "Annual Meeting of the Association for Computational Linguistics",
                        "aliases": ["ACL"],
                    }
                ],
                "years": {"include": [2025]},
                "publication_types": {"include": ["full"]},
                "topics": {"include": ["multi-agent"]},
            },
        }
    )


def test_acl_provider_emits_all_requested_long_papers_before_topic_screening(
    fixture_server,
) -> None:
    fixture_server.serve_text(
        "/events/acl-2025/",
        (FIXTURES / "event.html").read_text(encoding="utf-8"),
    )
    provider = AclAnthologyDiscoveryProvider(
        client=fixture_server.client,
        event_template=fixture_server.url("/events/acl-{year}/"),
        production_hosts={fixture_server.host},
    )

    batch = provider.discover(request())

    assert [item.key for item in batch.candidates] == [
        "2025.acl-long.1",
        "2025.acl-long.2",
        "2025.acl-long.3",
    ]
    candidate = batch.candidates[0]
    assert candidate.abstract == "Multi-agent evolutionary collaboration."
    assert candidate.doi == "10.18653/v1/2025.acl-long.1"
    assert candidate.authors == ("Ada Lovelace", "Alan Turing")
    assert candidate.publication_type == "full"
    assert candidate.track == "long"
    assert candidate.keywords == (
        "evolutionary computation",
        "large language models",
    )
    assert batch.covered_slices == ("acl-anthology:2025",)
    assert batch.coverage[0].state == "complete"
    assert batch.coverage[0].records_fetched == 3
    assert batch.coverage[0].records_recognized == 3
    assert batch.diagnostics == ()


def test_acl_provider_marks_malformed_eligible_record_as_partial(fixture_server) -> None:
    fixture_server.serve_text(
        "/events/acl-2025/",
        '<article data-anthology-id="2025.acl-long.1">'
        '<h5><a href="/2025.acl-long.1/">Valid Paper</a></h5></article>'
        '<article data-anthology-id="2025.acl-long.2"></article>',
    )
    provider = AclAnthologyDiscoveryProvider(
        client=fixture_server.client,
        event_template=fixture_server.url("/events/acl-{year}/"),
        production_hosts={fixture_server.host},
    )

    batch = provider.discover(request())

    assert [item.title for item in batch.candidates] == ["Valid Paper"]
    assert batch.coverage[0].state == "partial"
    assert batch.coverage[0].records_recognized == 2
    assert batch.coverage[0].records_fetched == 1
    assert batch.diagnostics[0].error_code == "page_contract_changed"


def test_acl_provider_reports_page_drift_without_copying_page_body(fixture_server) -> None:
    fixture_server.serve_text(
        "/events/acl-2025/",
        "<html><body>secret page body without articles</body></html>",
    )
    provider = AclAnthologyDiscoveryProvider(
        client=fixture_server.client,
        event_template=fixture_server.url("/events/acl-{year}/"),
        production_hosts={fixture_server.host},
    )

    batch = provider.discover(request())

    assert batch.candidates == ()
    assert batch.covered_slices == ()
    assert batch.coverage[0].state == "failed"
    assert len(batch.diagnostics) == 1
    assert batch.diagnostics[0].error_code == "page_contract_changed"
    assert batch.diagnostics[0].year == 2025
    assert "secret" not in batch.diagnostics[0].message


def test_acl_provider_parses_current_volume_list_structure(fixture_server) -> None:
    fixture_server.serve_text(
        "/events/acl-2025/",
        (FIXTURES / "event-current.html").read_text(encoding="utf-8"),
    )
    provider = AclAnthologyDiscoveryProvider(
        client=fixture_server.client,
        event_template=fixture_server.url("/events/acl-{year}/"),
        production_hosts={fixture_server.host},
    )

    batch = provider.discover(request())

    assert batch.diagnostics == ()
    assert [item.key for item in batch.candidates] == [
        "2025.acl-long.1",
        "2025.acl-long.2",
    ]
    assert batch.candidates[0].authors == ("Ada Lovelace", "Alan Turing")
    assert batch.candidates[0].abstract == "Multi-agent evolutionary collaboration."


def test_acl_capabilities_are_scoped_without_core_venue_logic() -> None:
    provider = AclAnthologyDiscoveryProvider(client=None)  # type: ignore[arg-type]

    capabilities = provider.capabilities()

    assert capabilities.provider_id == "acl-anthology"
    assert capabilities.source_class == "official_index"
    assert "ACL" in capabilities.venue_aliases
    assert {"title", "abstract", "authors", "venue"}.issubset(
        capabilities.evidence_fields
    )


def test_acl_provider_uses_requested_year_specific_venue(fixture_server) -> None:
    fixture_server.serve_text(
        "/events/acl-2025/",
        (FIXTURES / "event-current.html").read_text(encoding="utf-8"),
    )
    year_specific = DiscoveryRequest.from_spec(
        {
            "name": "acl",
            "target": {"minimum": 1, "preferred": 1, "maximum": 10},
            "scope": {
                "venues": [
                    {
                        "name": "Proceedings of the 63rd Annual Meeting of the Association for Computational Linguistics (Volume 1: Long Papers)",
                        "aliases": ["ACL"],
                    }
                ],
                "years": {"include": [2025]},
                "publication_types": {"include": ["proceedings-article"]},
                "topics": {"include": ["multi-agent"]},
            },
        }
    )
    provider = AclAnthologyDiscoveryProvider(
        client=fixture_server.client,
        event_template=fixture_server.url("/events/acl-{year}/"),
        production_hosts={fixture_server.host},
    )

    batch = provider.discover(year_specific)

    assert len(batch.candidates) == 2
    assert batch.candidates[0].venue == year_specific.venues[0].name


def test_acl_provider_keeps_missing_abstract_for_metadata_enrichment(fixture_server) -> None:
    fixture_server.serve_text(
        "/events/acl-2025/",
        (FIXTURES / "event.html").read_text(encoding="utf-8"),
    )
    provider = AclAnthologyDiscoveryProvider(
        client=fixture_server.client,
        event_template=fixture_server.url("/events/acl-{year}/"),
        production_hosts={fixture_server.host},
    )

    batch = provider.discover(request())

    missing = next(item for item in batch.candidates if item.key == "2025.acl-long.3")
    assert missing.abstract == ""
    assert "abstract" not in missing.evidence_fields
