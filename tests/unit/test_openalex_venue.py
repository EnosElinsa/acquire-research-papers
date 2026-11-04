from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from acquire_research_papers.discovery.contracts import CandidateMetadata, CandidatePage, DiscoveryRequest
from acquire_research_papers.discovery.openalex import OpenAlexClient
from acquire_research_papers.discovery.providers import (
    CrossrefVenueDiscoveryProvider,
    OpenAlexVenueDiscoveryProvider,
)
from acquire_research_papers.http import NetworkTransient, SafeHttpClient
from acquire_research_papers.source_catalog import describe_sources
from acquire_research_papers.specs import SpecValidationError, load_corpus_spec

INFOCOM = "IEEE Conference on Computer Communications (INFOCOM)"


def request(*, sources=("S7407087743",), issn=()) -> DiscoveryRequest:
    return DiscoveryRequest.from_spec({
        "name": "ieee conferences",
        "target": {"minimum": 1, "preferred": 5, "maximum": 10},
        "scope": {"venues": [{"name": "INFOCOM", "kind": "conference", "publisher": "IEEE",
                              "openalex_source": list(sources), "issn": list(issn)}],
                  "years": {"include": [2024]}, "topics": {"include": ["edge computing"]}},
    })


def work(index: int) -> CandidateMetadata:
    return CandidateMetadata(f"W{index}", f"Paper {index}", 2024, INFOCOM, 0.5, True,
                             ("title", "abstract"), doi=f"10.1109/infocom.2024.{index}",
                             abstract="An abstract", provenance={"source": "openalex"})


def test_every_page_of_a_declared_source_is_enumerated_under_the_spec_venue_name():
    calls = []

    def searcher(source_id, year, *, cursor, per_page):
        calls.append((source_id, year, cursor))
        if cursor == "*":
            return CandidatePage((work(1), work(2)), next_cursor="next", total_results=3)
        return CandidatePage((work(3),), next_cursor="later", total_results=3)

    batch = OpenAlexVenueDiscoveryProvider(searcher).discover(request())

    assert calls == [("S7407087743", 2024, "*"), ("S7407087743", 2024, "next")]
    assert [candidate.venue for candidate in batch.candidates] == ["INFOCOM"] * 3
    assert batch.candidates[0].provenance["reported_venue"] == INFOCOM
    (slice_,) = batch.coverage
    assert (slice_.provider_id, slice_.state, slice_.records_recognized) == ("openalex-venue", "complete", 3)


def test_a_missing_key_is_reported_as_configuration_and_a_transient_failure_as_retryable():
    missing = OpenAlexVenueDiscoveryProvider(lambda *a, **k: pytest.fail("no request"),
                                             configured=False).discover(request())
    assert missing.coverage[0].state == "failed"
    assert missing.diagnostics[0].error_code == "configuration_required"

    def unavailable(*args, **kwargs):
        raise NetworkTransient("down")

    transient = OpenAlexVenueDiscoveryProvider(unavailable).discover(request())
    assert transient.coverage[0].state == "failed"
    assert transient.diagnostics[0].retryable is True


def test_completed_slices_and_venues_without_sources_are_skipped():
    provider = OpenAlexVenueDiscoveryProvider(lambda *a, **k: pytest.fail("no request"))
    assert provider.discover(request(sources=())).coverage == ()
    resumed = request().with_completed_slices(frozenset({"openalex-venue:INFOCOM:2024"}))
    assert provider.discover(resumed).coverage == ()


def test_crossref_leaves_an_openalex_conference_alone_but_still_enumerates_by_issn():
    def searcher(*args, **kwargs):
        return CandidatePage(())

    crossref = CrossrefVenueDiscoveryProvider(searcher)
    assert crossref.discover(request()).coverage == ()
    assert crossref.discover(request()).diagnostics == ()
    assert crossref.discover(request(issn=("0743-166X",))).coverage[0].state == "complete"


def test_the_client_requests_one_source_year_and_keeps_the_key_out_of_provenance():
    seen = []

    def handler(http_request: httpx.Request) -> httpx.Response:
        seen.append(http_request.url)
        return httpx.Response(200, json={
            "meta": {"count": 1, "next_cursor": None},
            "results": [{"id": "https://openalex.org/W1", "title": "Paper", "publication_year": 2024,
                         "doi": "https://doi.org/10.1109/X.1", "type": "conference-paper",
                         "abstract_inverted_index": {"Edge": [0], "caching": [1]},
                         "primary_location": {"source": {"display_name": INFOCOM},
                                              "raw_source_name": "IEEE INFOCOM 2024",
                                              "landing_page_url": "https://doi.org/10.1109/X.1"},
                         "authorships": [{"author": {"display_name": "Ada Lovelace"}}]}]})

    client = SafeHttpClient(allowed_hosts={"api.openalex.org"})
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    page = OpenAlexClient(client=client, api_key="secret-key").source_works("S7407087743", 2024)

    query = parse_qs(urlsplit(str(seen[0])).query)
    assert query["filter"] == ["primary_location.source.id:S7407087743,publication_year:2024"]
    assert query["api_key"] == ["secret-key"]
    (candidate,) = page.candidates
    assert (candidate.doi, candidate.abstract) == ("10.1109/x.1", "Edge caching")
    assert candidate.provenance["raw_source_name"] == "IEEE INFOCOM 2024"
    assert "secret-key" not in candidate.provenance["query_url"]
    with pytest.raises(ValueError, match="source IDs"):
        OpenAlexClient(client=client, api_key="k").source_works("INFOCOM", 2024)


def test_the_spec_accepts_only_source_ids_and_sources_reports_the_route(tmp_path: Path):
    spec = tmp_path / "spec.yaml"
    body = ("mode: corpus\nname: ieee\ntarget: {{minimum: 1, maximum: 5}}\nscope:\n"
            "  venues:\n    - {{name: INFOCOM, kind: conference, publisher: IEEE, "
            "openalex_source: [{source}]}}\n  years: {{include: [2024]}}\n")
    spec.write_text(body.format(source="S7407087743"), encoding="utf-8")
    (slice_,) = describe_sources(load_corpus_spec(spec))["requested_slices"]
    assert slice_["openalex_venue"] == {"available": True, "sources": ["S7407087743"],
                                        "credentials": "OpenAlex API key"}
    assert slice_["crossref"]["diagnostic"] == "enumerated_by_openalex_source"

    spec.write_text(body.format(source="INFOCOM"), encoding="utf-8")
    with pytest.raises(SpecValidationError):
        load_corpus_spec(spec)


def lagging_searcher(count: int):
    def searcher(source_id, year, *, cursor, per_page):
        return CandidatePage(tuple(work(index) for index in range(count)), total_results=count)
    return searcher


def lag_request(year: int = 2025) -> DiscoveryRequest:
    value = request()
    return value.with_scope(value.venues, (year,))


def test_an_edition_far_below_the_previous_year_is_complete_but_warned_about():
    asked = []

    def counter(source_id, year):
        asked.append((source_id, year))
        return 262

    batch = OpenAlexVenueDiscoveryProvider(lagging_searcher(25), counter=counter).discover(lag_request())

    assert asked == [("S7407087743", 2024)]
    (slice_,) = batch.coverage
    assert (slice_.state, slice_.records_recognized) == ("complete", 25)
    (warning,) = batch.diagnostics
    assert (warning.error_code, warning.retryable, warning.venue, warning.year) == (
        "possible_upstream_lag", False, "INFOCOM", 2025)
    assert "25 works for INFOCOM 2025 against 262 for 2024" in warning.message


@pytest.mark.parametrize(("current", "previous"), [(200, 262), (10, 40)])
def test_a_normal_year_or_a_small_previous_year_gives_no_warning(current, previous):
    provider = OpenAlexVenueDiscoveryProvider(lagging_searcher(current),
                                              counter=lambda source_id, year: previous)
    assert provider.discover(lag_request()).diagnostics == ()


def test_the_lag_check_is_best_effort_and_skipped_for_an_unfinished_slice():
    def unavailable(source_id, year):
        raise NetworkTransient("down")

    quiet = OpenAlexVenueDiscoveryProvider(lagging_searcher(25), counter=unavailable)
    assert quiet.discover(lag_request()).diagnostics == ()

    def failing(*args, **kwargs):
        raise NetworkTransient("down")

    failed = OpenAlexVenueDiscoveryProvider(
        failing, counter=lambda *a: pytest.fail("no count for a failed slice"))
    assert [item.error_code for item in failed.discover(lag_request()).diagnostics] == [
        "network_transient"]


def test_the_client_counts_one_source_year_with_a_single_small_request():
    seen = []

    def handler(http_request: httpx.Request) -> httpx.Response:
        seen.append(http_request.url)
        return httpx.Response(200, json={"meta": {"count": 262}, "results": [{"id": "W1"}]})

    client = SafeHttpClient(allowed_hosts={"api.openalex.org"})
    client._client = httpx.Client(transport=httpx.MockTransport(handler))

    assert OpenAlexClient(client=client, api_key="k").source_count("S7407087743", 2024) == 262
    query = parse_qs(urlsplit(str(seen[0])).query)
    assert query["filter"] == ["primary_location.source.id:S7407087743,publication_year:2024"]
    assert (query["per-page"], query["select"]) == (["1"], ["id"])
    with pytest.raises(RuntimeError, match="not configured"):
        OpenAlexClient(client=client, api_key=None).source_count("S7407087743", 2024)
