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


def test_title_verification_ignores_inline_markup_from_discovery_metadata() -> None:
    metadata = PaperMetadata(
        title=(
            "Fast High-Diversity Subset Selection for Multiobjective Optimization "
            "by Riesz <italic>s</italic>-Energy"
        ),
        authors=("Ada Lovelace",),
        year=2025,
        venue="IEEE Transactions on Evolutionary Computation",
        doi="10.1109/tevc.2025.3570938",
        publisher="IEEE",
        landing_url="https://ieeexplore.ieee.org/document/11006112",
    )
    raw = (
        "@article{k,title={Fast High-Diversity Subset Selection for Multiobjective "
        "Optimization by Riesz s-Energy},author={Lovelace, Ada},year={2025},"
        "journal={IEEE Transactions on Evolutionary Computation},"
        "doi={10.1109/tevc.2025.3570938}}"
    )

    verify_bibliography(metadata, parse_bibtex(raw))


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


def test_proceedings_prefix_and_official_venue_suffix_are_equivalent() -> None:
    metadata = PaperMetadata(
        title="LLM-enhanced Score Function Evolution for Causal Structure Learning",
        authors=("Zidong Wang", "Fei Liu"),
        year=2025,
        venue="Thirty-Fourth International Joint Conference on Artificial Intelligence",
        doi="10.24963/ijcai.2025/1010",
        publisher="IJCAI",
        landing_url="https://www.ijcai.org/proceedings/2025/1010",
    )
    raw = (
        "@inproceedings{k,"
        "title={LLM-enhanced Score Function Evolution for Causal Structure Learning},"
        "author={Wang, Zidong and Liu, Fei},year={2025},"
        "booktitle={Proceedings of the Thirty-Fourth International Joint Conference "
        "on Artificial Intelligence, {IJCAI-25}},"
        "doi={10.24963/ijcai.2025/1010}}"
    )
    verify_bibliography(metadata, parse_bibtex(raw))


def test_author_identity_accepts_native_aliases_and_compound_surnames() -> None:
    metadata = PaperMetadata(
        title="Multilingual Author Identity",
        authors=(
            "Hu Zhang (张虎)",
            "Daniel Zhang-Li",
            "Anna Karen Gárate-Escamilla",
        ),
        year=2026,
        venue="Proceedings of the Test Conference",
        doi="10.1000/multilingual-authors",
        publisher="Test Publisher",
        landing_url="https://publisher.example/multilingual-authors",
    )
    raw = (
        "@inproceedings{k,title={Multilingual Author Identity},"
        "author={Zhang, Hu and Zhang-Li, Daniel and "
        "G{\\'a}rate-Escamilla, Anna Karen},year={2026},"
        "booktitle={Proceedings of the Test Conference},"
        "doi={10.1000/multilingual-authors}}"
    )

    verify_bibliography(metadata, parse_bibtex(raw))


def test_first_author_scope_accepts_complete_publisher_author_list() -> None:
    metadata = PaperMetadata(
        title="Farmers' cooperatives and smallholder farmers' access to credit: Evidence from China",
        authors=("Jiang",),
        authors_complete=False,
        year=2024,
        venue="Journal of Asian Economics",
        doi="10.1016/j.asieco.2024.101746",
        publisher="Elsevier",
        landing_url=(
            "https://www.sciencedirect.com/science/article/pii/S1049007824000411"
        ),
    )
    raw = (
        "@article{k,"
        "title={Farmers' cooperatives and smallholder farmers' access to credit: "
        "Evidence from China},"
        "author={Jiang, Ming and Paudel, Krishna and Mi, Yanbing},"
        "year={2024},journal={Journal of Asian Economics},"
        "doi={10.1016/j.asieco.2024.101746}}"
    )

    verify_bibliography(metadata, parse_bibtex(raw))


def test_first_author_scope_rejects_wrong_first_author() -> None:
    metadata = PaperMetadata(
        title="Verified Paper",
        authors=("Lovelace",),
        authors_complete=False,
        year=2026,
        venue="Test Venue",
        doi="10.1000/verified",
        publisher="Publisher",
        landing_url="https://publisher.example/verified",
    )
    raw = (
        "@article{k,title={Verified Paper},author={Turing, Alan and Lovelace, Ada},"
        "year={2026},journal={Test Venue},doi={10.1000/verified}}"
    )

    with pytest.raises(MetadataMismatch, match="author"):
        verify_bibliography(metadata, parse_bibtex(raw))
