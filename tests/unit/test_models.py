import pytest

from acquire_research_papers.models import ErrorCode, PaperMetadata, PaperStatus, normalize_doi


def test_normalize_doi_removes_url_and_prefix() -> None:
    assert normalize_doi("https://doi.org/10.1109/TEST.1") == "10.1109/test.1"
    assert normalize_doi("doi:10.1016/J.TEST.2026.1") == "10.1016/j.test.2026.1"


def test_metadata_normalizes_doi() -> None:
    metadata = PaperMetadata(
        title="Verified Paper",
        authors=("Ada Lovelace",),
        year=2026,
        venue="Test Venue",
        doi="https://doi.org/10.1109/TEST.1",
        publisher="Test Publisher",
        landing_url="https://publisher.example/paper",
    )
    assert metadata.doi == "10.1109/test.1"
    assert PaperStatus.PAIR_VERIFIED.value == "pair_verified"
    assert ErrorCode.BIB_MISSING.value == "bib_missing"


@pytest.mark.parametrize("field", ["title", "publisher", "landing_url"])
def test_metadata_rejects_missing_identity_fields(field: str) -> None:
    values = {
        "title": "Verified Paper",
        "authors": ("Ada Lovelace",),
        "year": 2026,
        "venue": "Test Venue",
        "doi": None,
        "publisher": "Test Publisher",
        "landing_url": "https://publisher.example/paper",
    }
    values[field] = ""
    with pytest.raises(ValueError, match=field):
        PaperMetadata(**values)


def test_metadata_requires_http_landing_url() -> None:
    with pytest.raises(ValueError, match="landing_url"):
        PaperMetadata(
            title="Verified Paper",
            authors=(),
            year=2026,
            venue="Test Venue",
            doi=None,
            publisher="Test Publisher",
            landing_url="file:///paper.pdf",
        )
