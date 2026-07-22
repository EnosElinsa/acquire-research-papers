from pathlib import Path

import pytest

from acquire_research_papers.artifacts import (
    InvalidPdfError,
    atomic_write_bytes,
    sanitize_artifact_value,
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


def test_artifact_sanitizer_removes_api_keys_and_signed_url_queries() -> None:
    sanitized = sanitize_artifact_value(
        {
            "api_key": "secret-one",
            "ApiKey": "secret-two",
            "nested": {"X-API-Key": "secret-three", "safe": "kept"},
            "api_url": "https://api.example/items?api_key=secret-four&page=2",
            "azure_url": "https://blob.example/item?sv=1&sig=secret-five",
            "google_url": (
                "https://storage.example/item?X-Goog-Credential=secret-six"
                "&X-Goog-Signature=secret-seven"
            ),
            "public_url": "https://example.test/items?page=2",
        }
    )

    assert sanitized == {
        "nested": {"safe": "kept"},
        "api_url": "https://api.example/items",
        "azure_url": "https://blob.example/item",
        "google_url": "https://storage.example/item",
        "public_url": "https://example.test/items?page=2",
    }
