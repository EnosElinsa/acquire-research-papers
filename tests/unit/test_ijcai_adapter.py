from pathlib import Path

from acquire_research_papers.acquisition.adapters.ijcai import IjcaiProceedingsAdapter


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_ijcai_resolves_visible_official_links(fixture_server) -> None:
    fixture_server.serve_text(
        "/proceedings/2025/1246",
        (FIXTURES / "ijcai" / "paper.html").read_text(encoding="utf-8"),
    )
    adapter = IjcaiProceedingsAdapter(
        client=fixture_server.client,
        production_hosts={fixture_server.host},
    )
    document = adapter.resolve(fixture_server.url("/proceedings/2025/1246"))
    assert document.metadata.doi == "10.24963/ijcai.2025/1246"
    assert document.metadata.publication_type == "demo"
    assert document.pdf_url == fixture_server.url("/proceedings/2025/1246.pdf")
    assert document.bibtex_url == fixture_server.url("/proceedings/2025/bibtex/1246")


def test_ijcai_rejects_demo_track_when_main_track_required(fixture_server) -> None:
    fixture_server.serve_text(
        "/proceedings/2025/1246",
        (FIXTURES / "ijcai" / "paper.html").read_text(encoding="utf-8"),
    )
    adapter = IjcaiProceedingsAdapter(
        client=fixture_server.client,
        production_hosts={fixture_server.host},
    )
    document = adapter.resolve(fixture_server.url("/proceedings/2025/1246"))
    assert not adapter.matches_track(document, allowed={"main", "regular"})
