import json
from pathlib import Path

import pytest
from werkzeug.wrappers import Response

from acquire_research_papers.discovery.crossref import CrossrefClient
from acquire_research_papers.discovery.openalex import OpenAlexClient
from acquire_research_papers.discovery.semantic_scholar import SemanticScholarClient
from acquire_research_papers.http import RateLimited, SafeHttpClient


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
    assert not hasattr(page.candidates[0], "bibtex")


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
