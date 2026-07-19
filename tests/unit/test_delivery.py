import json
from dataclasses import replace
from pathlib import Path

import pytest

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


def test_delivery_records_and_reuses_manual_acquisition_provenance(
    tmp_path: Path,
    verified_pair,
) -> None:
    delivery = GenericDelivery(tmp_path / "out")
    extra = {
        "acquisition_method": "manual_publisher_download",
        "metadata_source_url": "https://api.elsevier.com/content/search/scopus?query=PII(test)",
        "metadata_author_scope": "first_author",
        "source_pdf_filename": "download.pdf",
        "source_bibtex_filename": "download.bib",
    }

    result = delivery.deliver(
        pair=verified_pair,
        paper_id="paper-1",
        provenance_extra=extra,
    )

    provenance = json.loads(result.provenance.read_text(encoding="utf-8"))
    assert {key: provenance[key] for key in extra} == extra
    assert delivery.deliver(
        pair=verified_pair,
        paper_id="paper-1",
        provenance_extra=extra,
    ) == result


def test_delivery_rejects_reserved_provenance_before_writing_artifacts(
    tmp_path: Path,
    verified_pair,
) -> None:
    output = tmp_path / "out"

    with pytest.raises(ValueError, match="reserved"):
        GenericDelivery(output).deliver(
            pair=verified_pair,
            paper_id="paper-1",
            provenance_extra={"paper_id": "replacement"},
        )

    assert not output.exists()


def test_delivery_reuses_verbatim_crlf_bibtex_without_rewriting(
    tmp_path: Path,
    verified_pair,
) -> None:
    pair = replace(
        verified_pair,
        bibtex_text=verified_pair.bibtex_text.replace(",", ",\r\n"),
    )
    delivery = GenericDelivery(tmp_path / "out")
    result = delivery.deliver(pair=pair, paper_id="paper-1")
    first_provenance = result.provenance.read_bytes()

    assert delivery.deliver(pair=pair, paper_id="paper-1") == result

    assert result.bibtex.read_bytes() == pair.bibtex_text.encode("utf-8")
    assert result.provenance.read_bytes() == first_provenance
