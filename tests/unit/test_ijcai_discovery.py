from __future__ import annotations

from pathlib import Path

from acquire_research_papers.discovery.contracts import DiscoveryRequest
from acquire_research_papers.discovery.official.ijcai import IjcaiDiscoveryProvider


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "discovery" / "ijcai"
INDEX = FIXTURES / "index.html"
CURRENT_INDEX = FIXTURES / "index-current.html"
PAPER = FIXTURES / "paper.html"
CURRENT_PAPER = FIXTURES / "paper-current.html"
UNRELATED_PAPER = FIXTURES / "paper-unrelated.html"


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


def test_ijcai_provider_fetches_every_main_track_detail_before_topic_screening(
    fixture_server,
) -> None:
    fixture_server.serve_text(
        "/proceedings/2025/", INDEX.read_text(encoding="utf-8")
    )
    fixture_server.serve_text(
        "/proceedings/2025/12", PAPER.read_text(encoding="utf-8")
    )
    fixture_server.serve_text(
        "/proceedings/2025/13", UNRELATED_PAPER.read_text(encoding="utf-8")
    )

    batch = provider(fixture_server).discover(request())

    assert [item.key for item in batch.candidates] == [
        "10.24963/ijcai.2025/12",
        "10.24963/ijcai.2025/13",
    ]
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
    assert batch.coverage[0].state == "complete"
    assert batch.coverage[0].records_fetched == 2
    assert batch.coverage[0].records_recognized == 2
    assert batch.diagnostics == ()


def test_ijcai_provider_marks_malformed_index_record_as_partial(
    fixture_server,
) -> None:
    index = (
        "<h2>Main Track</h2>"
        '<div class="paper_wrapper"><a href="/proceedings/2025/12">'
        "Evolutionary Optimization for Large Language Models</a></div>"
        '<div class="paper_wrapper"><div class="title">Missing Link</div></div>'
    )
    fixture_server.serve_text("/proceedings/2025/", index)
    fixture_server.serve_text(
        "/proceedings/2025/12", PAPER.read_text(encoding="utf-8")
    )

    batch = provider(fixture_server).discover(request())

    assert len(batch.candidates) == 1
    assert batch.coverage[0].state == "partial"
    assert batch.coverage[0].records_recognized == 2
    assert batch.coverage[0].records_fetched == 1
    assert batch.diagnostics[0].error_code == "page_contract_changed"


def test_ijcai_provider_parses_current_index_title_and_details_layout(
    fixture_server,
) -> None:
    fixture_server.serve_text(
        "/proceedings/2025/", CURRENT_INDEX.read_text(encoding="utf-8")
    )
    fixture_server.serve_text(
        "/proceedings/2025/12", CURRENT_PAPER.read_text(encoding="utf-8")
    )
    fixture_server.serve_text(
        "/proceedings/2025/13", UNRELATED_PAPER.read_text(encoding="utf-8")
    )

    batch = provider(fixture_server).discover(request())

    assert [item.key for item in batch.candidates] == [
        "10.24963/ijcai.2025/12",
        "10.24963/ijcai.2025/13",
    ]
    assert batch.candidates[0].abstract == (
        "We optimize a large language model with evolutionary search when N<Nr."
    )
    assert batch.candidates[0].keywords == (
        "Large Language Models: Prompt optimization",
        "Evolutionary Computation: Evolutionary optimization",
    )
    assert batch.covered_slices == ("ijcai-proceedings:2025:Main Track",)
    assert batch.diagnostics == ()


def test_ijcai_provider_decodes_nested_html_entities_in_metadata_title(
    fixture_server,
) -> None:
    index = (
        '<div class="section_title"><h3>Main Track</h3></div>'
        '<div class="paper_wrapper">'
        '<div class="title">MSCI: Addressing CLIP\'s Inherent Limitations</div>'
        '<a href="/proceedings/2025/12">Details</a></div>'
    )
    paper = CURRENT_PAPER.read_text(encoding="utf-8").replace(
        "Evolutionary Optimization for Large Language Models",
        "MSCI: Addressing CLIP&amp;#039;s Inherent Limitations",
    )
    fixture_server.serve_text("/proceedings/2025/", index)
    fixture_server.serve_text("/proceedings/2025/12", paper)

    batch = provider(fixture_server).discover(request())

    assert [item.title for item in batch.candidates] == [
        "MSCI: Addressing CLIP's Inherent Limitations"
    ]
    assert batch.coverage[0].state == "complete"
    assert batch.diagnostics == ()


def test_ijcai_provider_treats_every_section_title_as_a_track_boundary(
    fixture_server,
) -> None:
    index = (
        '<div class="section" id="section0">'
        '<div class="section_title"><h3>Main Track</h3></div>'
        '<div class="paper_wrapper"><div class="title">Main Paper</div>'
        '<a href="/proceedings/2025/12">Details</a></div></div>'
        '<div class="section" id="section1">'
        '<div class="section_title"><h3>AI4Tech: AI Enabling Technologies</h3></div>'
        '<div class="paper_wrapper"><div class="title">AI4Tech Paper</div>'
        '<a href="/proceedings/2025/1015">Details</a></div></div>'
    )
    main_paper = CURRENT_PAPER.read_text(encoding="utf-8").replace(
        "Evolutionary Optimization for Large Language Models", "Main Paper"
    )
    fixture_server.serve_text("/proceedings/2025/", index)
    fixture_server.serve_text("/proceedings/2025/12", main_paper)

    batch = provider(fixture_server).discover(request())

    assert [item.title for item in batch.candidates] == ["Main Paper"]
    assert batch.coverage[0].pages_fetched == 2
    assert batch.coverage[0].state == "complete"
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
    assert batch.coverage[0].state == "partial"
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
    assert batch.coverage[0].state == "failed"
    assert len(batch.diagnostics) == 1
    assert batch.diagnostics[0].phase == "proceedings-index"


def test_ijcai_provider_uses_requested_year_specific_venue(fixture_server) -> None:
    fixture_server.serve_text(
        "/proceedings/2025/", INDEX.read_text(encoding="utf-8")
    )
    fixture_server.serve_text(
        "/proceedings/2025/12", PAPER.read_text(encoding="utf-8")
    )
    fixture_server.serve_text(
        "/proceedings/2025/13", UNRELATED_PAPER.read_text(encoding="utf-8")
    )
    venue_name = (
        "Proceedings of the Thirty-Fourth International Joint Conference "
        "on Artificial Intelligence"
    )
    year_specific = DiscoveryRequest.from_spec(
        {
            "name": "ijcai",
            "target": {"minimum": 1, "preferred": 1, "maximum": 10},
            "scope": {
                "venues": [{"name": venue_name, "aliases": ["IJCAI"]}],
                "years": {"include": [2025]},
                "publication_types": {"include": ["proceedings-article"]},
                "topics": {"include": ["evolutionary optimization"]},
            },
        }
    )

    batch = provider(fixture_server).discover(year_specific)

    assert len(batch.candidates) == 2
    assert batch.candidates[0].venue == venue_name


def test_ijcai_provider_keeps_published_year_when_new_year_is_unavailable(
    fixture_server,
) -> None:
    fixture_server.server.expect_request("/proceedings/2026/").respond_with_data(
        "not published",
        status=404,
    )
    fixture_server.serve_text(
        "/proceedings/2025/", INDEX.read_text(encoding="utf-8")
    )
    fixture_server.serve_text(
        "/proceedings/2025/12", PAPER.read_text(encoding="utf-8")
    )
    fixture_server.serve_text(
        "/proceedings/2025/13", UNRELATED_PAPER.read_text(encoding="utf-8")
    )
    multi_year = DiscoveryRequest.from_spec(
        {
            "name": "ijcai",
            "target": {"minimum": 1, "maximum": 10},
            "scope": {
                "venues": [{"name": "IJCAI", "aliases": ["IJCAI"]}],
                "years": {"include": [2026, 2025]},
                "publication_types": {"include": ["main"]},
                "topics": {"include": ["evolutionary optimization"]},
            },
        }
    )

    batch = provider(fixture_server).discover(multi_year)

    assert [item.year for item in batch.candidates] == [2025, 2025]
    assert batch.covered_slices == ("ijcai-proceedings:2025:Main Track",)
    assert len(batch.diagnostics) == 1
    assert batch.diagnostics[0].year == 2026
    assert batch.coverage[0].venue == "IJCAI"
    assert batch.coverage[1].venue == "IJCAI"
