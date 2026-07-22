import json
from pathlib import Path

import pytest
from werkzeug.wrappers import Response

from acquire_research_papers.discovery.contracts import (
    CandidateMetadata,
    CandidatePage,
    DiscoveryRequest,
)
from acquire_research_papers.discovery.crossref import CrossrefClient
from acquire_research_papers.discovery.openalex import OpenAlexClient
from acquire_research_papers.discovery.providers import CrossrefVenueDiscoveryProvider
from acquire_research_papers.discovery.semantic_scholar import SemanticScholarClient
from acquire_research_papers.http import NetworkTransient, RateLimited, SafeHttpClient


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "discovery"


def test_crossref_cursor_search_returns_candidate_only_metadata(fixture_server) -> None:
    fixture_server.serve_text(
        "/works",
        (FIXTURES / "crossref.json").read_text(encoding="utf-8"),
        "application/json",
    )
    client = CrossrefClient(client=fixture_server.client, endpoint=fixture_server.url("/works"))
    page = client.search(
        "evolutionary optimization",
        rows=10,
        cursor="*",
        filters={"from-pub-date": "2025-01-01"},
    )
    assert page.next_cursor == "next-cursor-token"
    assert page.candidates[0].doi == "10.1234/crossref.1"
    assert page.candidates[0].official_url == "https://publisher.example/article/1"
    assert "abstract" in page.candidates[0].evidence_fields
    assert page.candidates[0].keywords == (
        "Evolutionary computation",
        "Resource allocation",
    )
    assert page.candidates[0].field_provenance["keywords"] == ("crossref",)
    assert page.total_results == 1
    assert not hasattr(page.candidates[0], "bibtex")


def test_crossref_search_supports_container_title_and_issn_filters(fixture_server) -> None:
    payload = (FIXTURES / "crossref.json").read_text(encoding="utf-8")

    def handler(request):
        assert request.args["query.container-title"] == "Test Journal"
        assert "query.bibliographic" not in request.args
        assert request.args["rows"] == "250"
        filters = set(request.args["filter"].split(","))
        assert filters == {
            "from-pub-date:2025-01-01",
            "issn:1234-5678",
            "until-pub-date:2025-12-31",
        }
        assert "subject" in request.args["select"]
        assert "ISSN" in request.args["select"]
        return Response(payload, content_type="application/json")

    fixture_server.server.expect_request("/works").respond_with_handler(handler)
    client = CrossrefClient(client=fixture_server.client, endpoint=fixture_server.url("/works"))

    page = client.search(
        "Test Journal",
        rows=250,
        query_field="container-title",
        filters={
            "from-pub-date": "2025-01-01",
            "until-pub-date": "2025-12-31",
            "issn": "1234-5678",
        },
    )

    assert "query.container-title=Test+Journal" in page.query_url


def crossref_request() -> DiscoveryRequest:
    return DiscoveryRequest.from_spec(
        {
            "name": "venue enumeration",
            "target": {"minimum": 1, "preferred": 2, "maximum": 3},
            "scope": {
                "venues": [
                    {"name": "Journal A", "issn": ["1111-2222"]},
                    {"name": "Proceedings B"},
                ],
                "years": {"include": [2025]},
                "topics": {"include": ["must not become an enumeration query"]},
            },
        }
    )


def crossref_candidate(key: str, venue: str) -> CandidateMetadata:
    return CandidateMetadata(
        key=key,
        title=f"Paper {key}",
        year=2025,
        venue=venue,
        relevance_score=0.0,
        hard_gates_passed=True,
        evidence_fields=("title", "venue"),
        doi=f"10.1000/{key}",
        provenance={"source": "crossref"},
    )


def test_crossref_provider_enumerates_every_venue_year_cursor_without_topic_query() -> None:
    calls: list[dict] = []

    def searcher(query: str, **kwargs) -> CandidatePage:
        calls.append({"query": query, **kwargs})
        if query == "":
            assert kwargs["filters"]["issn"] == "1111-2222"
            if kwargs["cursor"] == "*":
                return CandidatePage(
                    (crossref_candidate("a1", "Journal A"),),
                    next_cursor="a-next",
                )
            return CandidatePage(())
        assert query == "Proceedings B"
        assert kwargs["query_field"] == "container-title"
        return CandidatePage((crossref_candidate("b1", "Proceedings B"),))

    batch = CrossrefVenueDiscoveryProvider(searcher=searcher, page_size=250).discover(
        crossref_request()
    )

    assert [candidate.key for candidate in batch.candidates] == ["a1", "b1"]
    assert len(calls) == 3
    assert all(call["rows"] == 250 for call in calls)
    assert all(
        call["filters"]["from-pub-date"] == "2025-01-01"
        and call["filters"]["until-pub-date"] == "2025-12-31"
        for call in calls
    )
    assert all("must not" not in call["query"] for call in calls)
    assert [coverage.state for coverage in batch.coverage] == ["complete", "complete"]
    assert [coverage.pages_fetched for coverage in batch.coverage] == [2, 1]
    assert batch.complete_slice_labels == (
        "crossref:Journal A:2025",
        "crossref:Proceedings B:2025",
    )


def test_crossref_provider_allows_same_cursor_for_distinct_scroll_pages() -> None:
    calls = 0

    def searcher(query: str, **kwargs) -> CandidatePage:
        nonlocal calls
        calls += 1
        if calls == 1:
            return CandidatePage(
                (crossref_candidate("a1", "Journal A"),),
                next_cursor="*",
                total_results=2,
            )
        return CandidatePage(
            (crossref_candidate("a2", "Journal A"),),
            next_cursor="*",
            total_results=2,
        )

    request = crossref_request().with_scope((crossref_request().venues[0],), (2025,))
    batch = CrossrefVenueDiscoveryProvider(searcher=searcher).discover(request)

    assert calls == 2
    assert [candidate.key for candidate in batch.candidates] == ["a1", "a2"]
    assert batch.coverage[0].state == "complete"
    assert batch.coverage[0].records_fetched == 2
    assert batch.diagnostics == ()


def test_crossref_provider_marks_repeated_page_partial_instead_of_looping() -> None:
    calls = 0

    def searcher(query: str, **kwargs) -> CandidatePage:
        nonlocal calls
        calls += 1
        return CandidatePage(
            (crossref_candidate("a1", "Journal A"),),
            next_cursor="*",
        )

    request = crossref_request().with_scope((crossref_request().venues[0],), (2025,))
    batch = CrossrefVenueDiscoveryProvider(searcher=searcher).discover(request)

    assert calls == 2
    assert batch.coverage[0].state == "partial"
    assert batch.coverage[0].records_fetched == 1
    assert batch.coverage[0].diagnostic_code == "repeated_page"
    assert batch.diagnostics[0].error_code == "repeated_page"


def test_crossref_provider_marks_network_failure_after_a_page_as_partial() -> None:
    calls = 0

    def searcher(query: str, **kwargs) -> CandidatePage:
        nonlocal calls
        calls += 1
        if calls == 1:
            return CandidatePage(
                (crossref_candidate("a1", "Journal A"),),
                next_cursor="second",
            )
        raise NetworkTransient("temporary")

    request = crossref_request().with_scope((crossref_request().venues[0],), (2025,))
    batch = CrossrefVenueDiscoveryProvider(searcher=searcher).discover(request)

    assert [candidate.key for candidate in batch.candidates] == ["a1"]
    assert batch.coverage[0].state == "partial"
    assert batch.coverage[0].next_cursor == "second"
    assert batch.coverage[0].diagnostic_code == "network_transient"
    assert batch.diagnostics[0].retryable


def test_crossref_provider_respects_venue_specific_year_scope() -> None:
    request = DiscoveryRequest.from_spec(
        {
            "name": "year editions",
            "target": {"minimum": 1, "maximum": 5},
            "scope": {
                "venues": [
                    {"name": "Conference 2024", "years": [2024]},
                    {"name": "Conference 2025", "years": [2025]},
                ],
                "years": {"include": [2025, 2024]},
            },
        }
    )
    calls: list[tuple[str, str]] = []

    def searcher(query: str, **kwargs) -> CandidatePage:
        calls.append((query, kwargs["filters"]["from-pub-date"]))
        return CandidatePage(())

    CrossrefVenueDiscoveryProvider(searcher=searcher).discover(request)

    assert calls == [
        ("Conference 2024", "2024-01-01"),
        ("Conference 2025", "2025-01-01"),
    ]


def test_crossref_rate_limit_is_classified(fixture_server) -> None:
    fixture_server.server.expect_request("/works").respond_with_data("limited", status=429)
    client = CrossrefClient(client=fixture_server.client, endpoint=fixture_server.url("/works"))
    with pytest.raises(RateLimited):
        client.search("test")


def test_openalex_reconstructs_abstract_and_related_ids(fixture_server) -> None:
    fixture_server.serve_text(
        "/works",
        (FIXTURES / "openalex.json").read_text(encoding="utf-8"),
        "application/json",
    )
    client = OpenAlexClient(
        client=fixture_server.client,
        endpoint=fixture_server.url("/works"),
        api_key="synthetic-key",
    )
    page = client.search("test", per_page=10)
    candidate = page.candidates[0]
    assert candidate.key == "W1"
    assert candidate.abstract == "OpenAlex abstract"
    assert candidate.related_ids == ("W2", "W3")
    assert page.next_cursor == "next-openalex"


def test_semantic_scholar_posts_positive_and_negative_seeds_without_logging_key(
    fixture_server,
) -> None:
    expected = json.loads((FIXTURES / "semantic-scholar.json").read_text(encoding="utf-8"))

    def handler(request):
        assert request.headers["x-api-key"] == "synthetic-key"
        assert request.get_json() == {
            "positivePaperIds": ["CorpusId:1"],
            "negativePaperIds": ["CorpusId:2"],
        }
        return Response(json.dumps(expected), content_type="application/json")

    fixture_server.server.expect_request("/recommendations", method="POST").respond_with_handler(
        handler
    )
    client = SemanticScholarClient(
        client=SafeHttpClient(allowed_hosts={fixture_server.host}),
        endpoint=fixture_server.url("/recommendations"),
        api_key="synthetic-key",
    )
    candidates = client.recommend(
        positive_ids=["CorpusId:1"],
        negative_ids=["CorpusId:2"],
        limit=25,
    )
    assert candidates[0].doi == "10.1234/s2.1"
    assert candidates[0].provenance["source"] == "semantic-scholar"


def test_semantic_scholar_search_uses_header_key_and_candidate_query(fixture_server) -> None:
    recommended = json.loads(
        (FIXTURES / "semantic-scholar.json").read_text(encoding="utf-8")
    )["recommendedPapers"]

    def handler(request):
        assert request.headers["x-api-key"] == "synthetic-key"
        assert request.args["query"] == "evolutionary language models"
        assert request.args["limit"] == "25"
        assert "paperId" in request.args["fields"]
        return Response(json.dumps({"data": recommended}), content_type="application/json")

    fixture_server.server.expect_request("/graph/search").respond_with_handler(handler)
    client = SemanticScholarClient(
        client=SafeHttpClient(allowed_hosts={fixture_server.host}),
        endpoint=fixture_server.url("/recommendations"),
        search_endpoint=fixture_server.url("/graph/search"),
        api_key="synthetic-key",
    )

    candidates = client.corpus_searcher("evolutionary language models", 25)

    assert candidates[0].doi == "10.1234/s2.1"
    assert "synthetic-key" not in candidates[0].provenance["query_url"]
    assert candidates[0].provenance["query_url"].startswith(
        fixture_server.url("/graph/search")
    )


def test_semantic_scholar_batches_doi_lookup_without_requiring_a_key(
    fixture_server,
) -> None:
    expected = json.loads(
        (FIXTURES / "semantic-scholar-batch.json").read_text(encoding="utf-8")
    )

    def handler(request):
        assert "x-api-key" not in request.headers
        assert request.get_json() == {
            "ids": ["DOI:10.1234/s2.1", "DOI:10.1234/missing"]
        }
        assert "abstract" in request.args["fields"]
        return Response(json.dumps(expected), content_type="application/json")

    fixture_server.server.expect_request("/graph/batch", method="POST").respond_with_handler(
        handler
    )
    client = SemanticScholarClient(
        client=SafeHttpClient(allowed_hosts={fixture_server.host}),
        batch_endpoint=fixture_server.url("/graph/batch"),
    )

    candidates = client.lookup_dois(["10.1234/s2.1", "10.1234/missing"])

    assert [candidate.doi for candidate in candidates] == ["10.1234/s2.1"]
    assert candidates[0].abstract == "A batch lookup abstract."
