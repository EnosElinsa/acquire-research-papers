from pathlib import Path

import pytest

from acquire_research_papers.artifacts import (
    InvalidPdfError,
    atomic_write_bytes,
    sha256_bytes,
    sha256_file,
    validate_pdf,
)


VALID_PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"


def test_pdf_header_and_hash(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(VALID_PDF)
    validate_pdf(pdf)
    assert len(sha256_file(pdf)) == 64
    assert sha256_file(pdf) == sha256_bytes(VALID_PDF)


def test_html_response_is_not_pdf(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_text("<html>login</html>", encoding="utf-8")
    with pytest.raises(InvalidPdfError, match="header"):
        validate_pdf(pdf)


def test_truncated_pdf_is_rejected(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.7\ntruncated")
    with pytest.raises(InvalidPdfError, match="EOF"):
        validate_pdf(pdf)


def test_atomic_pdf_write_commits_only_after_validation(tmp_path: Path) -> None:
    destination = tmp_path / "nested" / "paper.pdf"
    atomic_write_bytes(destination, VALID_PDF, validator=validate_pdf)
    assert destination.read_bytes() == VALID_PDF
    assert not destination.with_suffix(".pdf.partial").exists()


def test_atomic_pdf_write_removes_invalid_partial(tmp_path: Path) -> None:
    destination = tmp_path / "paper.pdf"
    with pytest.raises(InvalidPdfError):
        atomic_write_bytes(destination, b"<html>denied</html>", validator=validate_pdf)
    assert not destination.exists()
    assert not destination.with_suffix(".pdf.partial").exists()
