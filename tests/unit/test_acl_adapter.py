from pathlib import Path

from acquire_research_papers.acquisition.adapters.acl import AclAnthologyAdapter


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_acl_resolves_official_pdf_and_bib(fixture_server) -> None:
    fixture_server.serve_text(
        "/2025.acl-long.1/",
        (FIXTURES / "acl" / "paper.html").read_text(encoding="utf-8"),
    )
    adapter = AclAnthologyAdapter(
        client=fixture_server.client,
        production_hosts={fixture_server.host},
    )
    document = adapter.resolve(fixture_server.url("/2025.acl-long.1/"))
    assert document.metadata.title == "A Verified ACL Paper"
    assert document.metadata.publisher == "Association for Computational Linguistics"
    assert document.metadata.publication_type == "full"
    assert document.pdf_url == fixture_server.url("/2025.acl-long.1.pdf")
    assert document.bibtex_url == fixture_server.url("/2025.acl-long.1.bib")
    assert document.allowed_hosts == frozenset({fixture_server.host})


def test_acl_rejects_page_with_wrong_anthology_pdf(fixture_server) -> None:
    html = (FIXTURES / "acl" / "paper.html").read_text(encoding="utf-8")
    html = html.replace("2025.acl-long.1.pdf", "2025.acl-long.999.pdf")
    fixture_server.serve_text("/2025.acl-long.1/", html)
    adapter = AclAnthologyAdapter(
        client=fixture_server.client,
        production_hosts={fixture_server.host},
    )
    from acquire_research_papers.acquisition.base import PageContractChanged

    try:
        adapter.resolve(fixture_server.url("/2025.acl-long.1/"))
    except PageContractChanged as exc:
        assert "PDF" in str(exc)
    else:
        raise AssertionError("wrong ACL PDF was accepted")
