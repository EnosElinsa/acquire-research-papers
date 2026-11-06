"""discover candidates: topic search across venues with filters, time limits, and stops."""
from __future__ import annotations

import _thread
import json
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from acquire_research_papers.capability_cli import preset_issns, request_for
from acquire_research_papers.cli import Application, run_cli
from acquire_research_papers.discovery.contracts import (
    CandidateMetadata,
    DiscoveryBatch,
    DiscoveryCapabilities,
    DiscoveryRequest,
)
from acquire_research_papers.discovery.coordinator import DiscoveryCoordinator
from acquire_research_papers.discovery.crossref import CrossrefClient
from acquire_research_papers.discovery.openalex import OpenAlexClient
from acquire_research_papers.discovery.providers import (
    FilteredQueryProvider,
    matches_query_filters,
    query_filters,
    title_term_matches,
)
from acquire_research_papers.discovery.semantic_scholar import (
    SemanticScholarClient,
    SemanticScholarRequestPacer,
)


def paper(key: str, title: str = "A Survey of Mobile Robot Path Planning", *, year: int = 2024,
          doi: str | None = None, venue: str = "IEEE Transactions on Robotics",
          publication_type: str = "journal-article", source: str = "crossref",
          types: tuple[str, ...] = ()) -> CandidateMetadata:
    provenance: dict = {"source": source}
    if types:
        provenance["publication_types"] = list(types)
    return CandidateMetadata(key=key, title=title, year=year, venue=venue, relevance_score=0.5,
                             hard_gates_passed=True, evidence_fields=("title",),
                             doi=doi or f"10.1109/{key}", publication_type=publication_type,
                             provenance=provenance)


@dataclass
class Provider:
    provider_id: str
    source_class: str
    batch: DiscoveryBatch = field(default_factory=DiscoveryBatch)
    delay: float = 0.0
    calls: int = 0

    def capabilities(self) -> DiscoveryCapabilities:
        return DiscoveryCapabilities(provider_id=self.provider_id, source_class=self.source_class)

    def discover(self, request: DiscoveryRequest) -> DiscoveryBatch:
        self.calls += 1
        deadline = time.monotonic() + self.delay
        while time.monotonic() < deadline:
            time.sleep(0.02)
        return self.batch


def test_venue_listings_do_not_run_without_a_requested_venue() -> None:
    # Unscoped, the ACL and IJCAI indexes listed every paper of each year (5,599 ACL papers
    # and one IJCAI page per paper for 2023-2026), so a topic search never finished.
    official = Provider("ijcai-proceedings", "official_index")
    crossref = Provider("crossref", "venue_enumerator")
    search = Provider("crossref-search", "metadata_api", DiscoveryBatch((paper("a"),)))
    events: list[tuple[str, dict]] = []
    coordinator = DiscoveryCoordinator([official, crossref, search],
                                       progress=lambda event, details: events.append(
                                           (event, details)))

    batch = coordinator.discover(request_for("path planning survey", years=[2024]))

    assert (official.calls, crossref.calls, search.calls) == (0, 0, 1)
    assert [c.key for c in batch.candidates] == ["a"]
    assert ("provider_skipped", {"provider": "ijcai-proceedings"}) in events


def test_a_slow_provider_is_abandoned_after_its_time_limit_and_the_others_still_run() -> None:
    slow = Provider("semantic-scholar-search", "metadata_api", DiscoveryBatch((paper("slow"),)),
                    delay=5.0)
    fast = Provider("crossref-search", "metadata_api", DiscoveryBatch((paper("fast"),)))
    started = time.monotonic()

    batch = DiscoveryCoordinator([slow, fast]).discover(
        request_for("path planning"), provider_timeout_seconds=0.3)

    assert time.monotonic() - started < 3
    assert [c.key for c in batch.candidates] == ["fast"]
    (diagnostic,) = batch.diagnostics
    assert (diagnostic.provider_id, diagnostic.error_code, diagnostic.retryable) == (
        "semantic-scholar-search", "provider_timeout", True)


def test_a_stop_request_returns_the_candidates_found_so_far() -> None:
    first = Provider("crossref-search", "metadata_api", DiscoveryBatch((paper("first"),)))
    blocked = Provider("openalex-search", "metadata_api", DiscoveryBatch((paper("late"),)),
                       delay=10.0)
    never = Provider("semantic-scholar-search", "metadata_api", DiscoveryBatch((paper("x"),)))
    # job stop interrupts the main thread exactly like this.
    threading.Timer(0.4, _thread.interrupt_main).start()

    batch = DiscoveryCoordinator([first, blocked, never]).discover(
        request_for("path planning"), partial_on_interrupt=True)

    assert batch.interrupted
    assert [c.key for c in batch.candidates] == ["first"]
    assert never.calls == 0
    assert batch.diagnostics[-1].error_code == "interrupted"


def test_without_partial_results_a_stop_still_raises() -> None:
    blocked = Provider("crossref-search", "metadata_api", delay=10.0)
    threading.Timer(0.3, _thread.interrupt_main).start()
    with pytest.raises(KeyboardInterrupt):
        DiscoveryCoordinator([blocked]).discover(request_for("x"), provider_timeout_seconds=30)


def test_title_terms_match_at_word_starts_and_alternatives_are_ored() -> None:
    assert title_term_matches("Reviews of Path Planning", "review")
    assert title_term_matches("Path-planning for robots", "path planning")
    assert not title_term_matches("A Preview of Planning", "review")
    assert title_term_matches("Motion Planning: The State-of-the-Art", "survey|state of the art")


def test_filters_keep_years_doi_prefixes_title_terms_and_reviews() -> None:
    filters = query_filters(publication_types=["review"], doi_prefixes=["10.1109"],
                            title_terms=["path planning|motion planning"])
    request = request_for("mobile robot path planning", years=[2023, 2025], filters=filters)

    assert matches_query_filters(paper("ok", year=2025), request)
    assert not matches_query_filters(paper("old", year=2024), request)
    assert not matches_query_filters(paper("acm", doi="10.1145/x", year=2025), request)
    assert not matches_query_filters(paper("t", "Path Following Control", year=2025), request)
    article = paper("art", "Path Planning With Deep Learning", year=2025)
    assert not matches_query_filters(article, request)
    # A source's own review type counts, also after merging with another source's record.
    typed = paper("typed", "Path Planning With Deep Learning", year=2025,
                  source="semantic-scholar", types=("JournalArticle", "Review"))
    assert matches_query_filters(typed, request)
    merged = replace(article, source_records=(dict(article.provenance), dict(typed.provenance)))
    assert matches_query_filters(merged, request)
    # Crossref's peer-review type is a referee report, not a review article.
    assert not matches_query_filters(
        paper("pr", "Path planning report", year=2025, publication_type="peer-review"), request)


@pytest.mark.parametrize("arguments, message", [
    ({"publication_types": ["article"]}, "--type"),
    ({"doi_prefixes": ["ieee"]}, "--doi-prefix"),
    ({"issns": ["15523098"]}, "--issn"),
    ({"title_terms": ["|"]}, "--title-term"),
])
def test_filter_values_are_validated(arguments, message) -> None:
    with pytest.raises(ValueError, match=message):
        query_filters(**arguments)


def test_presets_supply_journal_issns_and_venues_by_short_name() -> None:
    assert preset_issns(["T-RO", "ieee-ral"]) == ["1552-3098", "1941-0468", "2377-3766"]
    with pytest.raises(ValueError, match="unknown --preset"):
        preset_issns(["Journal of Nothing"])
    with pytest.raises(ValueError, match="no ISSN"):
        preset_issns(["INFOCOM"])
    (venue,) = request_for("x", venues=["RA-L"]).venues
    assert venue.issn == ("2377-3766",) and venue.preset == "ieee-ral"


def test_a_source_without_an_issn_filter_is_skipped_when_journals_are_requested() -> None:
    called = []
    provider = FilteredQueryProvider("semantic-scholar-search",
                                     lambda *args: called.append(args) or (), issn_filter=False)
    request = request_for("x", filters=query_filters(issns=["1552-3098"]))

    batch = provider.discover(request)

    assert not called
    assert batch.diagnostics[0].error_code == "filter_unsupported"


def test_filtered_search_drops_records_outside_the_filters_and_unescapes_names() -> None:
    results = (paper("a", "Robots &amp; Path Planning: A Survey",
                     venue="IEEE Robotics &amp; Automation Magazine"),
               paper("b", "Unrelated Article"))
    provider = FilteredQueryProvider("crossref-search", lambda query, rows, request: results)
    request = request_for(["q1", "q2"], filters=query_filters(publication_types=["review"]))

    batch = provider.discover(request)

    assert [c.key for c in batch.candidates] == ["a", "a"]  # once per query
    assert batch.candidates[0].title == "Robots & Path Planning: A Survey"
    assert batch.candidates[0].venue == "IEEE Robotics & Automation Magazine"


class Recorder:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.urls: list[str] = []

    def get(self, url, headers=None):
        self.urls.append(url)
        payload = self.payload

        class Response:
            def json(self):
                return payload
        return Response()


def test_crossref_search_filters_server_side_and_keeps_the_contact_address_private() -> None:
    client = Recorder({"message": {"items": [{"DOI": "10.1109/x", "title": ["T"],
                                              "published": {"date-parts": [[2024]]}}]}})
    crossref = CrossrefClient(client=client, mailto="user@example.org")  # type: ignore[arg-type]
    request = request_for("path planning", years=[2025, 2023], filters=query_filters(
        doi_prefixes=["10.1109"], issns=["1552-3098", "2377-3766"]))

    (candidate,) = crossref.filtered_search("path planning", 50, request)

    query = parse_qs(urlsplit(client.urls[0]).query)
    assert query["query.bibliographic"] == ["path planning"]
    assert query["rows"] == ["50"]
    assert query["mailto"] == ["user@example.org"]
    assert query["filter"] == ["from-pub-date:2023-01-01,issn:1552-3098,issn:2377-3766,"
                               "prefix:10.1109,until-pub-date:2025-12-31"]
    assert "user@example.org" not in candidate.provenance["query_url"]


def test_openalex_search_filters_years_and_issns_and_records_the_work_type() -> None:
    client = Recorder({"results": [{"id": "https://openalex.org/W1", "title": "T",
                                    "publication_year": 2024, "type": "review"}],
                       "meta": {"next_cursor": None}})
    openalex = OpenAlexClient(client=client, api_key="k")  # type: ignore[arg-type]
    request = request_for("q", years=[2024, 2023], filters=query_filters(issns=["1552-3098"]))

    (candidate,) = openalex.filtered_search("q", 30, request)

    query = parse_qs(urlsplit(client.urls[0]).query)
    assert query["filter"] == ["publication_year:2023|2024,primary_location.source.issn:1552-3098"]
    assert query["per-page"] == ["30"]
    assert candidate.provenance["publication_types"] == ["review"]
    assert "api_key" not in candidate.provenance["query_url"]


def test_semantic_scholar_search_sends_the_year_range() -> None:
    client = Recorder({"data": [{"paperId": "p", "title": "T", "year": 2024,
                                 "publicationTypes": ["Review"]}]})
    semantic = SemanticScholarClient(client=client,  # type: ignore[arg-type]
                                     request_pacer=SemanticScholarRequestPacer(
                                         minimum_interval_seconds=0))

    (candidate,) = semantic.filtered_search("q", 500, request_for("q", years=[2026, 2023]))

    query = parse_qs(urlsplit(client.urls[0]).query)
    assert (query["year"], query["limit"]) == (["2023-2026"], ["100"])
    assert candidate.provenance["publication_types"] == ["Review"]


def test_the_command_writes_filtered_records_and_reports_the_filters(tmp_path: Path,
                                                                    capsys) -> None:
    received: list[DiscoveryRequest] = []

    class Coordinator:
        def discover(self, request, **options):
            received.append(request)
            assert options == {"provider_timeout_seconds": 45.0, "partial_on_interrupt": True,
                               "parallel_search": True}
            return DiscoveryBatch((paper("keep", year=2025),
                                   paper("drop", "Path Planning Article", year=2025)))

    application = Application.for_test(app_root=tmp_path / "app",
                                       repository_root=tmp_path / "repository")
    application.candidate_coordinator = Coordinator()  # type: ignore[assignment]
    output = tmp_path / "out" / "candidates.json"
    code = run_cli(["discover", "candidates", "--query", "mobile robot path planning",
                    "--year", "2025", "--type", "review", "--doi-prefix", "10.1109",
                    "--preset", "T-RO", "--title-term", "path planning", "--provider-timeout",
                    "45", "--output", str(output), "--result-file", str(tmp_path / "r.json")],
                   application=application)

    printed = json.loads(capsys.readouterr().out)
    written = json.loads(output.read_text(encoding="utf-8"))
    assert code == 0
    assert [record["key"] for record in written["records"]] == ["keep"]
    assert written["filters"] == {"queries": ["mobile robot path planning"], "years": [2025],
                                  "publication_types": ["review"], "doi_prefixes": ["10.1109"],
                                  "issns": ["1552-3098", "1941-0468"],
                                  "title_terms": ["path planning"],
                                  "venue_names": ["IEEE Transactions on Robotics"]}
    assert written["records"][0]["provenance"]["search_match"]["matched_terms"] == [
        "mobile", "path", "plann", "robot"]
    assert received[0].query_filters.issns == ("1552-3098", "1941-0468")
    assert json.loads((tmp_path / "r.json").read_text(encoding="utf-8")) == printed


def test_ranking_drops_topic_noise_and_orders_by_match() -> None:
    from acquire_research_papers.discovery.ranking import rank, topic_terms

    assert topic_terms("A comprehensive survey of mobile robot path planning") == (
        "mobile", "robot", "path", "plann")
    noise = replace(paper("noise", "A Survey of Proxy Re-Encryption"),
                    abstract="Proxy re-encryption lets a proxy transform ciphertexts.")
    partial_match = replace(paper("partial", "Path Following for Ground Vehicles"),
                            abstract="We study path tracking.")
    full = replace(paper("full", "Mobile Robot Path Planners: A Review"),
                   abstract="Robots plan paths.")
    unknown = paper("unknown", "An Overview of Embodied Agents")  # no abstract to judge

    ranked, dropped = rank([noise, partial_match, unknown, full],
                           ["mobile robot path planning survey"])

    assert [c.key for c in ranked] == ["full", "partial", "unknown"]
    assert dropped == 1
    # Title words count twice: 4 of 4 in the title, 2 of 4 ("robots", "paths") in the abstract.
    assert ranked[0].provenance["search_match"]["score"] == 0.833
    kept, none_dropped = rank([noise], ["mobile robot path planning"], keep_unmatched=True)
    assert [c.key for c in kept] == ["noise"] and none_dropped == 0


def test_keyword_searches_of_different_services_run_side_by_side() -> None:
    first = Provider("crossref-search", "metadata_api", DiscoveryBatch((paper("a"),)), delay=1.5)
    second = Provider("openalex-search", "metadata_api", DiscoveryBatch((paper("b"),)), delay=1.5)
    started = time.monotonic()

    batch = DiscoveryCoordinator([first, second]).discover(
        request_for("path planning"), provider_timeout_seconds=30, parallel_search=True)

    # One after the other they would take 3 s.
    assert time.monotonic() - started < 2.7
    assert [c.key for c in batch.candidates] == ["a", "b"]  # provider order, not finish order


def test_a_side_by_side_search_past_its_time_limit_keeps_the_finished_sources() -> None:
    slow = Provider("semantic-scholar-bulk", "metadata_api", DiscoveryBatch((paper("s"),)),
                    delay=5.0)
    fast = Provider("crossref-search", "metadata_api", DiscoveryBatch((paper("f"),)))

    batch = DiscoveryCoordinator([slow, fast]).discover(
        request_for("x"), provider_timeout_seconds=0.5, parallel_search=True)

    assert [c.key for c in batch.candidates] == ["f"]
    assert [d.error_code for d in batch.diagnostics] == ["provider_timeout"]


def test_a_rate_limited_search_is_retried_once_after_the_requested_delay() -> None:
    from acquire_research_papers.http import RateLimited

    calls: list[int] = []
    delays: list[float] = []

    def searcher(query, rows, request):
        calls.append(1)
        if len(calls) == 1:
            raise RateLimited(429, "https://api.crossref.org/works", retry_after_seconds=2)
        return (paper("a"),)

    batch = FilteredQueryProvider("crossref-search", searcher, sleeper=delays.append).discover(
        request_for("x"))

    assert (len(calls), delays, len(batch.candidates)) == (2, [2.0], 1)
    assert batch.covered_slices == ("crossref-search",)


def test_semantic_scholar_searches_preset_journals_by_name() -> None:
    filters = query_filters(issns=preset_issns(["T-RO", "RA-L"]))
    assert filters.venue_names == ("IEEE Transactions on Robotics",
                                   "IEEE Robotics and Automation Letters")
    assert query_filters(issns=["1552-3098", "9999-9999"]).venue_names == ()
    client = Recorder({"data": [], "token": None})
    semantic = SemanticScholarClient(client=client,  # type: ignore[arg-type]
                                     request_pacer=SemanticScholarRequestPacer(
                                         minimum_interval_seconds=0))
    provider = FilteredQueryProvider("semantic-scholar-bulk", semantic.bulk_search,
                                     issn_filter=False, name_filter=True)

    batch = provider.discover(request_for("path planning", years=[2024], filters=filters))

    query = parse_qs(urlsplit(client.urls[0]).query)
    assert urlsplit(client.urls[0]).path.endswith("/paper/search/bulk")
    assert query["venue"] == ["IEEE Transactions on Robotics,IEEE Robotics and Automation Letters"]
    assert (query["year"], query["sort"]) == (["2024"], ["citationCount:desc"])
    assert not batch.diagnostics


def test_semantic_scholar_bulk_search_follows_its_continuation_token() -> None:
    class Pages(Recorder):
        def get(self, url, headers=None):
            self.urls.append(url)
            page = len(self.urls)
            payload = {"data": [{"paperId": f"p{page}-{i}", "title": "T", "year": 2024}
                                for i in range(2)], "token": "next" if page == 1 else None}

            class Response:
                def json(self):
                    return payload
            return Response()

    client = Pages({})
    semantic = SemanticScholarClient(client=client,  # type: ignore[arg-type]
                                     request_pacer=SemanticScholarRequestPacer(
                                         minimum_interval_seconds=0))

    found = semantic.bulk_search("q", 3, request_for("q"))

    assert [c.key for c in found] == ["p1-0", "p1-1", "p2-0"]
    assert "token=next" in client.urls[1]


def test_rerunning_the_same_search_keeps_finished_sources(tmp_path: Path, capsys) -> None:
    calls: list[DiscoveryRequest] = []

    class Coordinator:
        def discover(self, request, **options):
            calls.append(request)
            if len(calls) == 1:  # Semantic Scholar timed out the first time
                return DiscoveryBatch((paper("a", "Mobile robot path planning survey"),),
                                      diagnostics=(),
                                      covered_slices=("crossref-search",))
            return DiscoveryBatch((paper("b", "Path planning for mobile robots: a review"),),
                                  covered_slices=("semantic-scholar-search",))

    application = Application.for_test(app_root=tmp_path / "app",
                                       repository_root=tmp_path / "repository")
    application.candidate_coordinator = Coordinator()  # type: ignore[assignment]
    command = ["discover", "candidates", "--query", "mobile robot path planning",
               "--output", str(tmp_path / "out.json")]

    def written() -> dict:
        return json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))

    run_cli(command, application=application)
    run_cli(command, application=application)
    second = written()
    run_cli([*command, "--fresh"], application=application)
    capsys.readouterr()

    assert calls[1].completed_slices == frozenset({"crossref-search"})
    assert [c.key for c in calls[1].seed_candidates] == ["a"]
    assert second["resumed"] is True
    assert sorted(record["key"] for record in second["records"]) == ["a", "b"]
    assert second["completed_sources"] == ["crossref-search", "semantic-scholar-search"]
    # --fresh searches every source again.
    assert calls[2].completed_slices == frozenset() and not calls[2].seed_candidates
    assert written()["resumed"] is False


def test_field_robotics_presets_name_the_ieee_successor_and_the_wiley_journal() -> None:
    from acquire_research_papers.discovery.venue_presets import find_preset

    assert find_preset("Field Robotics").id == "ieee-tfr"
    assert find_preset("T-FR").issn == ("2771-3989", "2997-1101")
    jfr = find_preset("Journal of Field Robotics")
    assert (jfr.id, jfr.publisher, jfr.issn) == ("wiley-jfr", "Wiley", ("1556-4959", "1556-4967"))
