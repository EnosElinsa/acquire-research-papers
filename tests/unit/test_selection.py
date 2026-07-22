from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from acquire_research_papers.discovery.contracts import CandidateMetadata, VenueScope
from acquire_research_papers.selection import SelectionStore, build_selection_records


def candidate(key: str = "paper", *, venue: str = "Invented Proceedings") -> CandidateMetadata:
    return CandidateMetadata(
        key,
        "Paper",
        2026,
        venue,
        0.95,
        True,
        ("title", "abstract"),
        doi=f"10.1000/{key}",
        official_url=f"https://publisher.example/{key}",
        authors=("Ada Lovelace",),
        abstract="Relevant abstract",
        keywords=("evolution",),
        publication_type="full",
        publication_date="2026-03-01",
    )


def numbered_delivery() -> dict[str, str]:
    return {
        "profile": "numbered",
        "naming_template": "2026.7.18 {publisher} {venue_short}/{number}.{ext}",
    }


def test_numbered_layout_is_metadata_driven_and_contiguous() -> None:
    venue = VenueScope(
        "Invented Proceedings",
        aliases=("IP Conference",),
        short_name="IP",
        publisher="Invented Society",
    )

    records = build_selection_records(
        [candidate(), candidate("paper-2", venue="IP Conference")],
        venues=(venue,),
        delivery=numbered_delivery(),
    )

    assert records[0].relative_pdf == "2026.7.18 Invented Society IP/1.pdf"
    assert records[0].relative_bibtex == "2026.7.18 Invented Society IP/1.bib"
    assert records[1].relative_pdf == "2026.7.18 Invented Society IP/2.pdf"
    assert records[1].relative_bibtex == "2026.7.18 Invented Society IP/2.bib"
    assert records[1].ordinal == 2


def test_numbering_restarts_for_each_rendered_parent() -> None:
    venues = (
        VenueScope("Venue A", short_name="A", publisher="Publisher"),
        VenueScope("Venue B", short_name="B", publisher="Publisher"),
    )

    records = build_selection_records(
        [candidate("a", venue="Venue A"), candidate("b", venue="Venue B")],
        venues=venues,
        delivery=numbered_delivery(),
    )

    assert records[0].relative_pdf.endswith("Publisher A/1.pdf")
    assert records[1].relative_pdf.endswith("Publisher B/1.pdf")


def test_numbered_layout_rejects_parent_traversal() -> None:
    with pytest.raises(ValueError, match="unsafe relative delivery path"):
        build_selection_records(
            [candidate()],
            venues=(VenueScope("Invented Proceedings", short_name="IP"),),
            delivery={
                "profile": "numbered",
                "naming_template": "../{number}.{ext}",
            },
        )


def test_numbered_layout_rejects_missing_metadata() -> None:
    with pytest.raises(ValueError, match="publisher"):
        build_selection_records(
            [candidate()],
            venues=(VenueScope("Invented Proceedings", short_name="IP"),),
            delivery=numbered_delivery(),
        )


def test_selection_store_round_trips_records_and_summary(tmp_path: Path) -> None:
    records = build_selection_records(
        [candidate()],
        venues=(
            VenueScope(
                "Invented Proceedings", short_name="IP", publisher="Invented Society"
            ),
        ),
        delivery=numbered_delivery(),
    )

    store = SelectionStore.write(
        tmp_path,
        {"name": "test"},
        records,
        discovery_summary={"provider_coverage": ["official:2026"]},
    )
    loaded = SelectionStore.load(store.manifest_path)

    assert loaded.records == records
    assert loaded.manifest["provider_coverage"] == ["official:2026"]
    assert loaded.manifest["selected_count"] == 1
    assert len(loaded.manifest["selected_sha256"]) == 64


def test_selection_store_rejects_modified_jsonl(tmp_path: Path) -> None:
    records = build_selection_records(
        [candidate()],
        venues=(
            VenueScope(
                "Invented Proceedings", short_name="IP", publisher="Invented Society"
            ),
        ),
        delivery=numbered_delivery(),
    )
    store = SelectionStore.write(tmp_path, {"name": "test"}, records)
    store.selected_path.write_text('{"selection_id":"changed"}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="selection SHA-256 mismatch"):
        SelectionStore.load(store.manifest_path)


def test_selection_store_rejects_modified_embedded_spec(tmp_path: Path) -> None:
    records = build_selection_records(
        [candidate()],
        venues=(
            VenueScope(
                "Invented Proceedings", short_name="IP", publisher="Invented Society"
            ),
        ),
        delivery=numbered_delivery(),
    )
    store = SelectionStore.write(tmp_path, {"name": "test"}, records)
    manifest = json.loads(store.manifest_path.read_text(encoding="utf-8"))
    manifest["spec"]["name"] = "changed"
    store.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="specification SHA-256 mismatch"):
        SelectionStore.load(store.manifest_path)


def test_selection_ids_are_stable_across_discovery_keys() -> None:
    original = candidate()
    duplicate = replace(original, key="source-specific-key")
    venue = VenueScope(
        "Invented Proceedings", short_name="IP", publisher="Invented Society"
    )

    first = build_selection_records(
        [original], venues=(venue,), delivery=numbered_delivery()
    )[0]
    second = build_selection_records(
        [duplicate], venues=(venue,), delivery=numbered_delivery()
    )[0]

    assert first.selection_id == second.selection_id
