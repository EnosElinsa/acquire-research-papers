from pathlib import Path

from acquire_research_papers.acquisition.adapters.acm import AcmDigitalLibraryAdapter


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_acm_requires_official_pdf_and_citation_export(fixture_server) -> None:
    fixture_server.serve_text(
        "/doi/10.1145/3711896.3736874",
        (FIXTURES / "acm" / "paper.html").read_text(encoding="utf-8"),
    )
    adapter = AcmDigitalLibraryAdapter(
        client=fixture_server.client,
        production_hosts={fixture_server.host},
    )
    document = adapter.resolve(fixture_server.url("/doi/10.1145/3711896.3736874"))
    assert document.metadata.publication_type == "research-article"
    assert document.pdf_url == fixture_server.url("/doi/pdf/10.1145/3711896.3736874")
    assert "/action/exportCiteProcCitation" in document.bibtex_url
    assert "format=bibTex" in document.bibtex_url


def test_acm_rejects_lookalike_hostname() -> None:
    adapter = AcmDigitalLibraryAdapter.for_production()
    assert adapter.supports("https://dl.acm.org/doi/10.1145/1")
    assert not adapter.supports("https://dl.acm.org.evil.example/doi/10.1145/1")
