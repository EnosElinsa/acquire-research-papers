import json
from pathlib import Path

from acquire_research_papers.delivery import GenericDelivery


def test_generic_delivery_is_atomic_and_reusable(tmp_path: Path, verified_pair) -> None:
    delivery = GenericDelivery(tmp_path / "out")
    result = delivery.deliver(pair=verified_pair, paper_id="paper-1")
    assert result.pdf.name == "paper.pdf"
    assert result.bibtex.name == "citation.bib"
    assert result.provenance.name == "provenance.json"
    assert result.status == "delivered"
    assert delivery.deliver(pair=verified_pair, paper_id="paper-1") == result


def test_delivery_preserves_raw_official_bibtex(tmp_path: Path, verified_pair) -> None:
    result = GenericDelivery(tmp_path / "out").deliver(
        pair=verified_pair,
        paper_id="paper-1",
    )
    assert result.bibtex.read_text(encoding="utf-8") == verified_pair.bibtex_text
    provenance = json.loads(result.provenance.read_text(encoding="utf-8"))
    assert provenance["paper_id"] == "paper-1"
    assert provenance["official_pdf_url"] == verified_pair.document.pdf_url
    assert provenance["official_bibtex_url"] == verified_pair.document.bibtex_url


def test_same_title_different_paper_ids_do_not_collide(tmp_path: Path, verified_pair) -> None:
    delivery = GenericDelivery(tmp_path / "out")
    first = delivery.deliver(pair=verified_pair, paper_id="paper-1")
    second = delivery.deliver(pair=verified_pair, paper_id="paper-2")
    assert first.pdf != second.pdf
