from pathlib import Path
from dataclasses import replace

import pytest

from acquire_research_papers.acquisition.adapters.sciencedirect import ScienceDirectAdapter
from acquire_research_papers.acquisition.adapters.sciencedirect_bridge import ScienceDirectBridgeResult
from acquire_research_papers.acquisition.base import AccessRequired, NotOfficial
from acquire_research_papers.bibliography import BibMissing


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def bridge_result(landing_url: str, *, bibtex: str | None = None) -> ScienceDirectBridgeResult:
    origin = landing_url.split("/science/article/", maxsplit=1)[0]
    pii = landing_url.rsplit("/", maxsplit=1)[-1]
    return ScienceDirectBridgeResult(
        pii=pii,
        title="A Restricted Elsevier Paper",
        authors=("Grace Hopper",),
        year=2025,
        venue="Test Journal",
        doi="10.1016/j.test.2025.1",
        publisher="Elsevier",
        landing_url=landing_url,
        pdf_url=f"{origin}/science/article/pii/{pii}/pdfft?download=true",
        bibtex_url=f"{origin}/sdfe/arp/cite?pii={pii}&format=text%2Fx-bibtex",
        access_pdf_url=(
            "https://www-sciencedirect-com-s.vpn.scau.edu.cn/"
            f"science/article/pii/{pii}/pdfft?download=true"
        ),
        access_bibtex_url=(
            "https://www-sciencedirect-com-s.vpn.scau.edu.cn/"
            f"sdfe/arp/cite?pii={pii}&format=text%2Fx-bibtex"
        ),
        pdf_bytes=b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n",
        bibtex=(
            bibtex
            if bibtex is not None
            else "@article{k,title={A Restricted Elsevier Paper},author={Hopper, Grace},"
            "year={2025},journal={Test Journal},doi={10.1016/j.test.2025.1}}"
        ),
    )


class StubScienceDirectBridge:
    def __init__(self, result: ScienceDirectBridgeResult) -> None:
        self.result = result
        self.calls: list[str] = []

    def retrieve(self, reference: str) -> ScienceDirectBridgeResult:
        self.calls.append(reference)
        return self.result


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


def test_sciencedirect_falls_back_once_when_direct_entitlement_is_missing(
    fixture_server,
) -> None:
    path = "/science/article/pii/S1049007824000411"
    fixture_server.serve_text(
        path,
        (FIXTURES / "sciencedirect" / "denied.html").read_text(encoding="utf-8"),
    )
    landing_url = fixture_server.url(path)
    bridge = StubScienceDirectBridge(bridge_result(landing_url))
    adapter = ScienceDirectAdapter(
        client=fixture_server.client,
        bridge=bridge,
        production_hosts={fixture_server.host},
    )
    document = adapter.resolve(landing_url)
    pair = adapter.acquire(document)
    assert bridge.calls == [landing_url]
    assert pair.document.metadata.title == "A Restricted Elsevier Paper"
    assert pair.bibtex_text.startswith("@article")


def test_sciencedirect_open_access_does_not_read_institutional_credentials(
    fixture_server,
) -> None:
    path = "/science/article/pii/S2210650225000884"
    fixture_server.serve_text(
        path,
        (FIXTURES / "sciencedirect" / "open.html").read_text(encoding="utf-8"),
    )
    landing_url = fixture_server.url(path)
    bridge = StubScienceDirectBridge(bridge_result(landing_url))
    adapter = ScienceDirectAdapter(
        client=fixture_server.client,
        bridge=bridge,
        production_hosts={fixture_server.host},
    )
    document = adapter.resolve(landing_url)
    assert document.metadata.title == "An Open Elsevier Paper"
    assert bridge.calls == []


def test_sciencedirect_institutional_pair_requires_raw_official_bibtex(fixture_server) -> None:
    path = "/science/article/pii/S1049007824000411"
    fixture_server.serve_text(
        path,
        (FIXTURES / "sciencedirect" / "denied.html").read_text(encoding="utf-8"),
    )
    landing_url = fixture_server.url(path)
    bridge = StubScienceDirectBridge(bridge_result(landing_url, bibtex=""))
    adapter = ScienceDirectAdapter(
        client=fixture_server.client,
        bridge=bridge,
        production_hosts={fixture_server.host},
    )
    with pytest.raises(BibMissing):
        adapter.resolve(landing_url)


def test_sciencedirect_rejects_institutional_proxy_lookalike(fixture_server) -> None:
    path = "/science/article/pii/S1049007824000411"
    fixture_server.serve_text(
        path,
        (FIXTURES / "sciencedirect" / "denied.html").read_text(encoding="utf-8"),
    )
    landing_url = fixture_server.url(path)
    result = replace(
        bridge_result(landing_url),
        access_pdf_url=(
            "https://www-sciencedirect-com-s.vpn.scau.edu.cn.evil.example/"
            "science/article/pii/S1049007824000411/pdfft"
        ),
    )
    adapter = ScienceDirectAdapter(
        client=fixture_server.client,
        bridge=StubScienceDirectBridge(result),
        production_hosts={fixture_server.host},
    )
    with pytest.raises(NotOfficial):
        adapter.resolve(landing_url)
