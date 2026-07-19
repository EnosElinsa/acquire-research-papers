from pathlib import Path

import pytest

from acquire_research_papers.artifacts import sha256_file
from acquire_research_papers.models import ErrorCode, PaperStatus
from acquire_research_papers.registry import Registry, StateTransitionError


def test_registry_deduplicates_normalized_doi(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "registry.sqlite")
    first = registry.upsert_paper(title="Paper", doi="https://doi.org/10.1109/TEST.1")
    second = registry.upsert_paper(title="Different casing", doi="10.1109/test.1")
    assert first == second


def test_registry_deduplicates_identity_when_doi_is_missing(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "registry.sqlite")
    first = registry.upsert_paper(
        title="  A Paper: With Punctuation! ",
        year=2026,
        first_author="Ada Lovelace",
        venue="IEEE Test",
    )
    second = registry.upsert_paper(
        title="a paper with punctuation",
        year=2026,
        first_author="Ada Lovelace",
        venue="IEEE Test",
    )
    assert first == second


def test_illegal_transition_is_rejected(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "registry.sqlite")
    paper_id = registry.upsert_paper(title="Paper", doi="10.1109/test.2")
    with pytest.raises(StateTransitionError):
        registry.transition(paper_id, PaperStatus.DELIVERED)


def test_error_event_preserves_last_successful_state(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "registry.sqlite")
    paper_id = registry.upsert_paper(title="Paper", doi="10.1109/test.3")
    registry.transition(paper_id, PaperStatus.AUTO_ACCEPTED)
    registry.record_error(paper_id, ErrorCode.NETWORK_TRANSIENT, "connection reset")
    assert registry.status(paper_id) is PaperStatus.AUTO_ACCEPTED
    assert registry.events(paper_id)[-1]["error_code"] == ErrorCode.NETWORK_TRANSIENT.value


def test_number_allocation_is_stable_and_gap_free(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "registry.sqlite")
    one = registry.create_verified_paper("One", "10.1109/one")
    two = registry.create_verified_paper("Two", "10.1109/two")
    assert registry.allocate_number("task", "IEEE TEVC", one) == 1
    assert registry.allocate_number("task", "IEEE TEVC", one) == 1
    assert registry.allocate_number("task", "IEEE TEVC", two) == 2


def test_registry_state_survives_reopen(tmp_path: Path) -> None:
    path = tmp_path / "registry.sqlite"
    first = Registry(path)
    paper_id = first.upsert_paper(title="Persistent", doi="10.1109/persistent")
    first.transition(paper_id, PaperStatus.AUTO_ACCEPTED)
    first.close()

    reopened = Registry(path)
    assert reopened.status(paper_id) is PaperStatus.AUTO_ACCEPTED
    assert reopened.journal_mode() == "wal"


def test_verified_delivery_reuse_rejects_tampered_artifacts(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "registry.sqlite")
    paper_id = registry.create_verified_paper("Cached", "10.1000/cached")
    registry.transition(paper_id, PaperStatus.DELIVERED)
    output = tmp_path / "out"
    output.mkdir()
    paths = {
        "pdf": output / "paper.pdf",
        "bibtex": output / "citation.bib",
        "provenance": output / "provenance.json",
    }
    paths["pdf"].write_bytes(b"%PDF-1.7\n%%EOF\n")
    paths["bibtex"].write_text("@article{k}\n", encoding="utf-8")
    paths["provenance"].write_text("{}\n", encoding="utf-8")
    for kind, path in paths.items():
        registry.record_artifact(
            paper_id,
            kind=kind,
            path=path,
            sha256=sha256_file(path),
            source_url=f"https://publisher.example/{kind}",
        )
    registry.record_provenance(
        paper_id,
        source="publisher",
        source_url="https://publisher.example/paper",
        payload={},
    )
    assert registry.verified_delivery("10.1000/cached", output) == paths

    paths["pdf"].write_bytes(b"tampered")
    assert registry.verified_delivery("10.1000/cached", output) is None
