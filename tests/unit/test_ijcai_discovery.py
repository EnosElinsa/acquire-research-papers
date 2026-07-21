from __future__ import annotations

from pathlib import Path

from acquire_research_papers.discovery.contracts import DiscoveryRequest
from acquire_research_papers.discovery.official.ijcai import IjcaiDiscoveryProvider


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "discovery" / "ijcai"
INDEX = FIXTURES / "index.html"
PAPER = FIXTURES / "paper.html"


def request() -> DiscoveryRequest:
    return DiscoveryRequest.from_spec(
        {
            "name": "ijcai",
            "target": {"minimum": 1, "preferred": 1, "maximum": 10},
            "scope": {
                "venues": [
                    {
                        "name": "International Joint Conference on Artificial Intelligence",
                        "aliases": ["IJCAI"],
                    }
                ],
                "years": {"include": [2025]},
                "publication_types": {"include": ["main"]},
                "topics": {"include": ["evolutionary optimization"]},
            },
        }
    )


def provider(fixture_server) -> IjcaiDiscoveryProvider:
    return IjcaiDiscoveryProvider(
        client=fixture_server.client,
        index_template=fixture_server.url("/proceedings/{year}/"),
        production_hosts={fixture_server.host},
    )


def test_ijcai_provider_prefilters_and_emits_main_track_detail(fixture_server) -> None:
    fixture_server.serve_text(
        "/proceedings/2025/", INDEX.read_text(encoding="utf-8")
    )
    fixture_server.serve_text(
        "/proceedings/2025/12", PAPER.read_text(encoding="utf-8")
    )

    batch = provider(fixture_server).discover(request())

    assert [item.key for item in batch.candidates] == ["10.24963/ijcai.2025/12"]
    candidate = batch.candidates[0]
    assert candidate.track == "Main Track"
    assert candidate.publication_type == "main"
    assert candidate.publication_date == "2025-08-01"
    assert "large language model" in candidate.abstract.casefold()
    assert candidate.keywords == (
        "large language model",
        "evolutionary optimization",
    )
    assert batch.covered_slices == ("ijcai-proceedings:2025:Main Track",)
    assert batch.diagnostics == ()


def test_ijcai_provider_isolates_malformed_relevant_detail(fixture_server) -> None:
    index = (
        "<h2>Main Track</h2>"
        '<div class="paper_wrapper"><a href="/proceedings/2025/11">'
        "Evolutionary Optimization Failure</a></div>"
        '<div class="paper_wrapper"><a href="/proceedings/2025/12">'
        "Evolutionary Optimization for Large Language Models</a></div>"
    )
    fixture_server.serve_text("/proceedings/2025/", index)
    fixture_server.serve_text(
        "/proceedings/2025/11", "<html>secret malformed detail body</html>"
    )
    fixture_server.serve_text(
        "/proceedings/2025/12", PAPER.read_text(encoding="utf-8")
    )

    batch = provider(fixture_server).discover(request())

    assert [item.key for item in batch.candidates] == ["10.24963/ijcai.2025/12"]
    assert len(batch.diagnostics) == 1
    assert batch.diagnostics[0].error_code == "page_contract_changed"
    assert batch.diagnostics[0].url.endswith("/proceedings/2025/11")
    assert "secret" not in batch.diagnostics[0].message


def test_ijcai_provider_reports_unrecognizable_index(fixture_server) -> None:
    fixture_server.serve_text(
        "/proceedings/2025/", "<html><body>new unrecognized layout</body></html>"
    )

    batch = provider(fixture_server).discover(request())

    assert batch.candidates == ()
    assert batch.covered_slices == ()
    assert len(batch.diagnostics) == 1
    assert batch.diagnostics[0].phase == "proceedings-index"
