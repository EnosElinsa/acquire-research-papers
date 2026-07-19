import pytest

from acquire_research_papers.acquisition.adapters.direct import DirectOfficialAdapter
from acquire_research_papers.acquisition.base import PageContractChanged
from acquire_research_papers.http import SafeHttpClient


def test_direct_adapter_resolves_and_acquires_official_pair(httpserver) -> None:
    html = """
    <html><head>
      <meta name="citation_title" content="An Official Paper">
      <meta name="citation_author" content="Ada Lovelace">
      <meta name="citation_publication_date" content="2026/01/02">
      <meta name="citation_journal_title" content="Test Journal">
      <meta name="citation_doi" content="10.1234/test.1">
      <meta name="citation_publisher" content="Test Publisher">
      <meta name="citation_pdf_url" content="/paper.pdf">
      <link rel="alternate" type="application/x-bibtex" href="/paper.bib">
    </head></html>
    """
    httpserver.expect_request("/paper").respond_with_data(html, content_type="text/html")
    httpserver.expect_request("/paper.pdf").respond_with_data(
        b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n", content_type="application/pdf"
    )
    httpserver.expect_request("/paper.bib").respond_with_data(
        "@article{k,title={An Official Paper},author={Lovelace, Ada},year={2026},"
        "journal={Test Journal},doi={10.1234/test.1}}",
        content_type="application/x-bibtex",
    )
    adapter = DirectOfficialAdapter(
        SafeHttpClient(allowed_hosts={httpserver.host}),
        production_hosts={httpserver.host},
    )
    document = adapter.resolve(httpserver.url_for("/paper"))
    pair = adapter.acquire(document)
    assert pair.document.metadata.title == "An Official Paper"
    assert pair.pdf_bytes.startswith(b"%PDF-")
    assert pair.bibtex_text.startswith("@article")


def test_direct_adapter_refuses_missing_official_bibtex(httpserver) -> None:
    html = """
    <meta name="citation_title" content="Incomplete">
    <meta name="citation_author" content="Ada Lovelace">
    <meta name="citation_publication_date" content="2026">
    <meta name="citation_journal_title" content="Test Journal">
    <meta name="citation_publisher" content="Test Publisher">
    <meta name="citation_pdf_url" content="/paper.pdf">
    """
    httpserver.expect_request("/paper").respond_with_data(html, content_type="text/html")
    adapter = DirectOfficialAdapter(
        SafeHttpClient(allowed_hosts={httpserver.host}),
        production_hosts={httpserver.host},
    )
    with pytest.raises(PageContractChanged, match="BibTeX"):
        adapter.resolve(httpserver.url_for("/paper"))
