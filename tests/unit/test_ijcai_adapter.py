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


def test_ijcai_parses_the_2026_layout_on_both_hosts() -> None:
    from acquire_research_papers.acquisition.adapters.ijcai import IJCAI_HOSTS
    from acquire_research_papers.http import SafeHttpClient

    html = (FIXTURES / "ijcai" / "paper-2026.html").read_text(encoding="utf-8")
    adapter = IjcaiProceedingsAdapter(SafeHttpClient(allowed_hosts=set(IJCAI_HOSTS)))

    for host in ("ijcai.org", "www.ijcai.org"):
        document = adapter.parse(f"https://{host}/proceedings/2023/1", html)

        assert document.pdf_url == f"https://{host}/proceedings/2023/0001.pdf"
        assert document.bibtex_url == f"https://{host}/proceedings/2023/bibtex/1"
        assert document.metadata.authors == ("Abdullah Al Maruf", "Luyao Niu")
        assert document.metadata.publication_type == "main"
        assert document.allowed_hosts == IJCAI_HOSTS  # www pages redirect files to ijcai.org
