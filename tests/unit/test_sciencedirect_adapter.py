from pathlib import Path

import pytest

from acquire_research_papers.acquisition.adapters.sciencedirect import ScienceDirectAdapter
from acquire_research_papers.acquisition.base import AccessRequired


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_sciencedirect_resolves_open_pdf_and_official_bibtex(fixture_server) -> None:
    fixture_server.serve_text(
        "/science/article/pii/S2210650225000884",
        (FIXTURES / "sciencedirect" / "open.html").read_text(encoding="utf-8"),
    )
    adapter = ScienceDirectAdapter(
        client=fixture_server.client,
        production_hosts={fixture_server.host},
    )
    document = adapter.resolve(fixture_server.url("/science/article/pii/S2210650225000884"))
    assert document.pdf_url.startswith(
        fixture_server.url("/science/article/pii/S2210650225000884/pdfft")
    )
    assert "/sdfe/arp/cite?" in document.bibtex_url
    assert "format=text%2Fx-bibtex" in document.bibtex_url


def test_sciencedirect_uses_current_campus_entitlement_link(fixture_server) -> None:
    fixture_server.serve_text(
        "/science/article/pii/S095741742600669X",
        (FIXTURES / "sciencedirect" / "subscribed.html").read_text(encoding="utf-8"),
    )
    adapter = ScienceDirectAdapter(
        client=fixture_server.client,
        production_hosts={fixture_server.host},
    )
    document = adapter.resolve(fixture_server.url("/science/article/pii/S095741742600669X"))
    assert document.metadata.title == "A Subscribed Elsevier Paper"
    assert document.pdf_url.startswith(
        fixture_server.url("/science/article/pii/S095741742600669X/pdfft")
    )


def test_sciencedirect_reports_missing_campus_entitlement(fixture_server) -> None:
    fixture_server.serve_text(
        "/science/article/pii/S0000000000000000",
        (FIXTURES / "sciencedirect" / "denied.html").read_text(encoding="utf-8"),
    )
    adapter = ScienceDirectAdapter(
        client=fixture_server.client,
        production_hosts={fixture_server.host},
    )
    with pytest.raises(AccessRequired):
        adapter.resolve(fixture_server.url("/science/article/pii/S0000000000000000"))
