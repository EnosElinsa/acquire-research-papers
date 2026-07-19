from pathlib import Path

import pytest

from acquire_research_papers.bibliography import (
    BibMissing,
    MetadataMismatch,
    parse_bibtex,
    verify_bibliography,
)
from acquire_research_papers.models import PaperMetadata


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "citations"


def verified_metadata() -> PaperMetadata:
    return PaperMetadata(
        title="Verified Paper: A Test",
        authors=("Ada Lovelace", "Alan Turing"),
        year=2026,
        venue="IEEE Test",
        doi="10.1109/test.1",
        publisher="IEEE",
        landing_url="https://ieeexplore.ieee.org/document/1",
    )


def test_official_bibtex_matches_metadata_and_preserves_raw() -> None:
    raw = (FIXTURES / "verified.bib.txt").read_text(encoding="utf-8")
    parsed = parse_bibtex(raw)
    verify_bibliography(verified_metadata(), parsed)
    assert parsed.raw == raw
    assert parsed.key == "verified2026"


def test_empty_bibtex_is_blocking() -> None:
    with pytest.raises(BibMissing):
        parse_bibtex("")


def test_multiple_bibtex_entries_are_rejected() -> None:
    raw = (
        "@article{one,title={One},year={2026}}\n"
        "@article{two,title={Two},year={2026}}\n"
    )
    with pytest.raises(MetadataMismatch, match="exactly one"):
        parse_bibtex(raw)


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        ("doi", "10.1109/wrong", "DOI"),
        ("year", "2025", "year"),
        ("title", "Completely Unrelated Work", "title"),
        ("journal", "Unrelated Venue", "venue"),
        ("author", "Hopper, Grace", "author"),
    ],
)
def test_metadata_mismatch_is_blocking(field: str, replacement: str, message: str) -> None:
    values = {
        "title": "Verified Paper: A Test",
        "author": "Lovelace, Ada and Turing, Alan",
        "year": "2026",
        "journal": "IEEE Test",
        "doi": "10.1109/TEST.1",
    }
    values[field] = replacement
    raw = (
        "@article{k,"
        f"title={{{values['title']}}},"
        f"author={{{values['author']}}},"
        f"year={{{values['year']}}},"
        f"journal={{{values['journal']}}},"
        f"doi={{{values['doi']}}}"
        "}"
    )
    with pytest.raises(MetadataMismatch, match=message):
        verify_bibliography(verified_metadata(), parse_bibtex(raw))
