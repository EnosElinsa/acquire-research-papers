from urllib.parse import urlsplit

from acquire_research_papers.acquisition.adapters.open_access import _CVF_PATH, _NEURIPS_PATH, _PMLR_PATH
from acquire_research_papers.discovery.contracts import (
    DiscoveryBatch,
    DiscoveryCapabilities,
    DiscoveryRequest,
)
from acquire_research_papers.discovery.coordinator import DiscoveryCoordinator
from acquire_research_papers.discovery.official.archives import (
    CvfIndexProvider,
    IclrIndexProvider,
    NeuripsIndexProvider,
    PmlrIndexProvider,
    UsenixIndexProvider,
)

MAIN, BENCH, DRIFT = "a" * 32, "b" * 32, "c" * 32


def request(venues, years, *, include_types=(), seeds=()):
    spec = {"name": "archive test", "target": {"minimum": 1, "maximum": 10},
            "scope": {"venues": venues, "years": {"include": list(years)},
                      "publication_types": {"include": list(include_types)}}}
    return DiscoveryRequest.from_spec(spec).with_seed_candidates(tuple(seeds))


def requested_paths(server) -> list[str]:
    return [entry[0].path for entry in server.log]


# ------------------------------------------------------------------ NeurIPS

NEURIPS_INDEX = f"""<html><body><ul class="paper-list">
<li class="conference" data-track="conference"><div class="paper-content">
<a href="/paper_files/paper/2023/hash/{MAIN}-Abstract-Conference.html" title="paper title">Graph Repair with Verified Tests</a>
<span class="paper-authors">Ada Lovelace, Alan Turing</span></div></li>
<li class="datasets_and_benchmarks" data-track="datasets_and_benchmarks"><div class="paper-content">
<a href="/paper_files/paper/2023/hash/{BENCH}-Abstract-Datasets_and_Benchmarks.html">A Benchmark of Verified Tests</a>
<span class="paper-authors">Grace Hopper</span></div></li>
<li class="conference"><div class="paper-content">
<a href="/paper_files/paper/2023/hash/{DRIFT}-Abstract-Conference.html">Listing Title</a></div></li>
</ul><ul class="nav"><li><a href="/">Home</a></li></ul></body></html>"""


def neurips_detail(title: str, authors: tuple[str, ...], doi: str) -> str:
    metas = "".join(f'<meta name="citation_author" content="{name}">' for name in authors)
    return (f'<html><head><meta name="citation_title" content="{title}">{metas}'
            f'<meta name="citation_doi" content="{doi}">'
            '<meta name="citation_publication_date" content="2023-12-15"></head><body>'
            '<h4>Abstract</h4><p class="paper-abstract"><p>Repairs graphs &amp; checks them.</p></p>'
            '</body></html>')


def neurips(fixture_server) -> NeuripsIndexProvider:
    server = fixture_server.server
    server.expect_request("/paper_files/paper/2023").respond_with_data(NEURIPS_INDEX, content_type="text/html")
    server.expect_request(f"/paper_files/paper/2023/hash/{MAIN}-Abstract-Conference.html").respond_with_data(
        neurips_detail("Graph Repair with Verified Tests", ("Lovelace, Ada", "Turing, Alan"),
                       "10.52202/075280-0001"), content_type="text/html")
    server.expect_request(f"/paper_files/paper/2023/hash/{BENCH}-Abstract-Datasets_and_Benchmarks.html"
                          ).respond_with_data(neurips_detail(
                              "A Benchmark of Verified Tests", ("Hopper, Grace",), "10.52202/075280-0002"),
                              content_type="text/html")
    server.expect_request(f"/paper_files/paper/2023/hash/{DRIFT}-Abstract-Conference.html").respond_with_data(
        neurips_detail("A Different Paper", ("Lovelace, Ada",), "10.52202/075280-0003"),
        content_type="text/html")
    return NeuripsIndexProvider(fixture_server.client,
                                index_template=fixture_server.url("/paper_files/paper/{year}"),
                                production_hosts={fixture_server.host})


def test_neurips_index_lists_both_tracks_with_landing_urls_for_acquisition(fixture_server) -> None:
    batch = neurips(fixture_server).discover(request([{"name": "NeurIPS"}], [2023]))

    by_title = {candidate.title: candidate for candidate in batch.candidates}
    main = by_title["Graph Repair with Verified Tests"]
    assert main.venue == "NeurIPS"
    assert main.doi == "10.52202/075280-0001"
    assert main.authors == ("Ada Lovelace", "Alan Turing")
    assert main.abstract == "Repairs graphs & checks them."
    assert main.publication_type == "proceedings-article"
    assert main.publication_date == "2023-12-15"
    assert _NEURIPS_PATH.fullmatch(urlsplit(main.official_url).path)
    assert by_title["A Benchmark of Verified Tests"].publication_type == "datasets-and-benchmarks"
    (coverage,) = batch.coverage
    assert (coverage.state, coverage.records_recognized, coverage.records_fetched) == ("partial", 3, 2)
    assert [(item.phase, item.error_code) for item in batch.diagnostics] == [
        ("paper-detail", "page_contract_changed")]


def test_neurips_skips_papers_outside_the_requested_track(fixture_server) -> None:
    provider = neurips(fixture_server)
    batch = provider.discover(request([{"name": "NeurIPS"}], [2023], include_types=["main"]))

    assert {candidate.publication_type for candidate in batch.candidates} == {"proceedings-article"}
    assert not any(BENCH in path for path in requested_paths(fixture_server.server))


def test_a_resumed_slice_reuses_paper_pages_read_by_the_earlier_run(fixture_server) -> None:
    provider = neurips(fixture_server)
    first = provider.discover(request([{"name": "NeurIPS"}], [2023]))
    detail_requests = sum("-Abstract" in path for path in requested_paths(fixture_server.server))

    again = provider.discover(request([{"name": "NeurIPS"}], [2023], seeds=first.candidates))

    assert {c.title for c in again.candidates} == {c.title for c in first.candidates}
    # Only the paper that failed before is read again.
    assert sum("-Abstract" in path for path in requested_paths(fixture_server.server)) == detail_requests + 1


def test_neurips_uses_listed_authors_when_a_paper_page_has_none(fixture_server) -> None:
    server = fixture_server.server
    server.expect_request("/paper_files/paper/2019").respond_with_data(
        f'<ul><li><div class="paper-content"><a href="/paper_files/paper/2019/hash/{MAIN}-Abstract.html">'
        'Visual Sequence Learning</a><span class="paper-authors">Ada Lovelace, Alan Turing</span></div></li></ul>',
        content_type="text/html")
    server.expect_request(f"/paper_files/paper/2019/hash/{MAIN}-Abstract.html").respond_with_data(
        neurips_detail("Visual Sequence Learning", (), "").replace(
            '<meta name="citation_doi" content="">', ""), content_type="text/html")
    provider = NeuripsIndexProvider(fixture_server.client,
                                    index_template=fixture_server.url("/paper_files/paper/{year}"),
                                    production_hosts={fixture_server.host})

    (candidate,) = provider.discover(request([{"name": "NeurIPS"}], [2019])).candidates

    assert candidate.authors == ("Ada Lovelace", "Alan Turing")
    assert candidate.doi is None


def test_a_year_without_proceedings_is_source_unavailable(fixture_server) -> None:
    fixture_server.server.expect_request("/paper_files/paper/2031").respond_with_data("missing", status=404)
    provider = NeuripsIndexProvider(fixture_server.client,
                                    index_template=fixture_server.url("/paper_files/paper/{year}"),
                                    production_hosts={fixture_server.host})
    batch = provider.discover(request([{"name": "NeurIPS"}], [2031]))
    assert batch.coverage[0].state == "failed"
    assert batch.diagnostics[0].error_code == "source_unavailable"
    assert not batch.diagnostics[0].retryable


# ------------------------------------------------------------------ PMLR

PMLR_INDEX = """<html><body><ul>
<li><a href="v235"><b>Volume 235</b></a> Proceedings of ICML 2024</li>
<li><a href="v251"><b>Volume 251</b></a> Proceedings of GRaM at ICML 2024</li>
<li><a href="v202"><b>Volume 202</b></a> Proceedings of ICML 2023</li>
<li><a href="v184"><b>Volume 184</b></a> Proceedings of ICML 2022 Workshop on Healthcare AI</li>
<li><a href="v48"><b>Volume 48</b></a> ICML 2016 Proceedings</li>
</ul></body></html>"""

PMLR_BIB = """


@Proceedings{ICML2023,
  title =     {Proceedings of the 40th International Conference on Machine Learning},
  volume =    202
}



@InProceedings{pmlr-v202-lovelace23a,
  title = \t {Verified Graphs \\& Tests on {GPU}s},
  author =       {Lovelace, Ada and Richt{\\'a}rik, Peter},
  booktitle = \t {Proceedings of the 40th International Conference on Machine Learning},
  year = \t {2023},
  url = \t {https://proceedings.mlr.press/v202/lovelace23a.html},
  abstract = \t {We study $k$-repair of graphs.}
}



@InProceedings{pmlr-v202-turing23b,
  title = \t {A Second Verified Paper},
  author =       {Turing, Alan},
  year = \t {2023},
  abstract = \t {Second abstract.}
}



@InProceedings{pmlr-v201-hopper23a,
  title = \t {Misfiled Paper},
  author =       {Hopper, Grace},
  year = \t {2023},
  abstract = \t {Belongs to another volume.}
}
"""


def pmlr(fixture_server) -> PmlrIndexProvider:
    fixture_server.server.expect_request("/").respond_with_data(PMLR_INDEX, content_type="text/html")
    fixture_server.server.expect_request("/v202/assets/bib/bibliography.bib").respond_with_data(
        PMLR_BIB, content_type="application/octet-stream")
    return PmlrIndexProvider(fixture_server.client, index_url=fixture_server.url("/"),
                             production_hosts={fixture_server.host})


def test_pmlr_reads_one_volume_bibliography_with_abstracts(fixture_server) -> None:
    batch = pmlr(fixture_server).discover(request([{"name": "ICML"}], [2023]))

    first, second = batch.candidates
    assert first.title == "Verified Graphs & Tests on GPUs"
    assert first.authors == ("Ada Lovelace", "Peter Richtárik")
    assert first.abstract == "We study $k$-repair of graphs."
    assert first.official_url == fixture_server.url("/v202/lovelace23a.html")
    assert _PMLR_PATH.fullmatch(urlsplit(first.official_url).path)
    assert first.doi is None and first.venue == "ICML"
    assert second.official_url == fixture_server.url("/v202/turing23b.html")
    (coverage,) = batch.coverage
    assert (coverage.state, coverage.records_recognized, coverage.records_fetched) == ("partial", 3, 2)
    assert requested_paths(fixture_server.server).count("/v202/assets/bib/bibliography.bib") == 1


def test_pmlr_never_mistakes_a_workshop_volume_for_the_conference(fixture_server) -> None:
    batch = pmlr(fixture_server).discover(
        request([{"name": "International Conference on Machine Learning"}], [2022, 2023]))

    states = {coverage.year: (coverage.state, coverage.diagnostic_code) for coverage in batch.coverage}
    assert states[2022] == ("failed", "source_unavailable")
    assert states[2023][0] == "partial"
    assert requested_paths(fixture_server.server).count("/") == 1  # front page read once


# ------------------------------------------------------------------ CVF

def cvf_listing(entries: list[tuple[str, str]]) -> str:
    items = "".join(
        f'<dt class="ptitle"><br><a href="{href}">{title}</a></dt><dd>'
        f'<form class="authsearch"><input type="hidden" name="query_author" value="Ada Lovelace"></form></dd>'
        f'<dd>[<a href="{href.replace("/html/", "/papers/").replace(".html", ".pdf")}">pdf</a>]</dd>'
        for href, title in entries
    )
    return f'<html><body><div id="content"><dl>{items}</dl></div></body></html>'


def cvf_detail(title: str, year: int) -> str:
    return (f'<html><head><meta name="citation_title" content="{title}">'
            '<meta name="citation_author" content="Lovelace, Ada">'
            f'<meta name="citation_publication_date" content="{year}"></head><body>'
            f'<div id="papertitle">{title}</div><div id="abstract">\n  Abstract of {title}.\n</div>'
            '</body></html>')


def test_cvf_lists_the_main_conference_and_checks_each_paper(fixture_server) -> None:
    server = fixture_server.server
    good = "/content/CVPR2023/html/Lovelace_Good_CVPR_2023_paper.html"
    stale = "/content/CVPR2023/html/Lovelace_Stale_CVPR_2023_paper.html"
    server.expect_request("/CVPR2023", query_string="day=all").respond_with_data(
        cvf_listing([(good, "Good Paper"), (stale, "Stale Paper")]), content_type="text/html")
    server.expect_request(good).respond_with_data(cvf_detail("Good Paper", 2023), content_type="text/html")
    server.expect_request(stale).respond_with_data(cvf_detail("Stale Paper", 2022), content_type="text/html")
    provider = CvfIndexProvider(fixture_server.client, origin=fixture_server.url("/"),
                                production_hosts={fixture_server.host})

    batch = provider.discover(request([{"name": "CVPR"}], [2023]))

    (candidate,) = batch.candidates
    assert (candidate.title, candidate.venue, candidate.authors) == ("Good Paper", "CVPR", ("Ada Lovelace",))
    assert candidate.abstract == "Abstract of Good Paper."
    assert _CVF_PATH.fullmatch(urlsplit(candidate.official_url).path)
    assert batch.coverage[0].state == "partial"


def test_cvf_reads_per_day_pages_of_older_conferences(fixture_server) -> None:
    server = fixture_server.server
    server.expect_request("/CVPR2019", query_string="day=all").respond_with_data(
        "<html><body>CVPR 2019</body></html>", content_type="text/html")
    server.expect_request("/CVPR2019", query_string="").respond_with_data(
        '<a href="CVPR2019.py?day=2019-06-18">Tue</a><a href="CVPR2019.py?day=2019-06-19">Wed</a>'
        '<a href="http://cvpr2019.thecvf.com">site</a>', content_type="text/html")
    for day, stem in (("2019-06-18", "Tue"), ("2019-06-19", "Wed")):
        path = f"/content_CVPR_2019/html/{stem}_Paper_CVPR_2019_paper.html"
        server.expect_request("/CVPR2019.py", query_string=f"day={day}").respond_with_data(
            cvf_listing([(path.lstrip("/"), f"{stem} Paper")]), content_type="text/html")
        server.expect_request(path).respond_with_data(cvf_detail(f"{stem} Paper", 2019),
                                                      content_type="text/html")
    provider = CvfIndexProvider(fixture_server.client, origin=fixture_server.url("/"),
                                production_hosts={fixture_server.host})

    batch = provider.discover(request([{"name": "CVPR"}], [2019]))

    assert sorted(candidate.title for candidate in batch.candidates) == ["Tue Paper", "Wed Paper"]
    assert batch.coverage[0].state == "complete"


def test_cvf_declines_a_venue_declared_as_ieee_and_reports_missing_years(fixture_server) -> None:
    fixture_server.server.expect_request("/WACV2019", query_string="day=all").respond_with_data(
        "missing", status=404)
    provider = CvfIndexProvider(fixture_server.client, origin=fixture_server.url("/"),
                                production_hosts={fixture_server.host})

    assert provider.discover(request([{"name": "CVPR", "publisher": "IEEE"}], [2023])) == DiscoveryBatch()
    batch = provider.discover(request([{"name": "WACV"}], [2019]))
    assert batch.diagnostics[0].error_code == "source_unavailable"


# ------------------------------------------------------------------ coordination

def test_a_complete_archive_slice_keeps_crossref_from_enumerating_it(fixture_server) -> None:
    calls = []

    class Crossref:
        def capabilities(self):
            return DiscoveryCapabilities(provider_id="crossref", source_class="venue_enumerator")

        def discover(self, scoped):
            calls.append([(venue.name, venue.years) for venue in scoped.venues])
            return DiscoveryBatch()

    fixture_server.server.expect_request("/").respond_with_data(PMLR_INDEX, content_type="text/html")
    fixture_server.server.expect_request("/v202/assets/bib/bibliography.bib").respond_with_data(
        PMLR_BIB.replace("pmlr-v201-hopper23a", "pmlr-v202-hopper23a"))
    provider = PmlrIndexProvider(fixture_server.client, index_url=fixture_server.url("/"),
                                 production_hosts={fixture_server.host})

    batch = DiscoveryCoordinator([Crossref(), provider]).discover(
        request([{"name": "ICML", "issn": ["2640-3498"]}], [2022, 2023]))

    assert len(batch.candidates) == 3
    assert calls == [[("ICML", (2022,))]]


def test_source_catalog_lists_archive_indexes_and_their_artifacts() -> None:
    from acquire_research_papers.source_catalog import describe_sources

    result = describe_sources({
        "name": "catalog", "target": {"minimum": 1, "maximum": 5},
        "scope": {"years": {"include": [2023]}, "venues": [
            {"name": "NeurIPS"}, {"name": "ICML"}, {"name": "CVPR"},
            {"name": "CVPR IEEE", "aliases": ["CVPR"], "publisher": "IEEE"}]}})
    slices = {row["venue"]: row for row in result["requested_slices"]}
    assert slices["NeurIPS"]["official_indexes"] == ["neurips-proceedings"]
    assert slices["ICML"]["acquisition"] == "official_pair_page_embedded_bibtex"
    assert slices["CVPR"]["official_indexes"] == ["cvf-open-access"]
    assert slices["CVPR"]["acquisition"] == "open_access_version_page_embedded_bibtex"
    assert slices["CVPR IEEE"]["official_indexes"] == []
    assert {"neurips-proceedings", "pmlr", "cvf-open-access"} <= {s["id"] for s in result["sources"]}


# ------------------------------------------------------------------ ICLR

def test_iclr_reads_the_proceedings_listing_from_2024(fixture_server) -> None:
    server = fixture_server.server
    server.expect_request("/paper_files/paper/2024").respond_with_data(
        f'<ul><li><div class="paper-content"><a href="/paper_files/paper/2024/hash/{MAIN}-Abstract-'
        'Conference.html">Verified Representation Tests</a><span class="paper-authors">Ada '
        'Lovelace, Alan Turing</span></div></li></ul>', content_type="text/html")
    server.expect_request(f"/paper_files/paper/2024/hash/{MAIN}-Abstract-Conference.html").respond_with_data(
        neurips_detail("Verified Representation Tests", ("Lovelace, Ada", "Turing, Alan"), "").replace(
            '<meta name="citation_doi" content="">', "").replace("2023-12-15", "2024-05-31"),
        content_type="text/html")
    provider = IclrIndexProvider(fixture_server.client,
                                 index_template=fixture_server.url("/paper_files/paper/{year}"),
                                 production_hosts={fixture_server.host})

    batch = provider.discover(request([{"name": "ICLR"}], [2024]))

    (candidate,) = batch.candidates
    assert (candidate.venue, candidate.authors, candidate.doi) == (
        "ICLR", ("Ada Lovelace", "Alan Turing"), None)
    assert candidate.abstract == "Repairs graphs & checks them."
    assert candidate.provenance["source"] == "iclr-proceedings"
    assert batch.coverage[0].state == "complete"


def test_iclr_before_2024_is_openreview_only_and_sends_no_request(fixture_server) -> None:
    provider = IclrIndexProvider(fixture_server.client,
                                 index_template=fixture_server.url("/paper_files/paper/{year}"),
                                 production_hosts={fixture_server.host})

    batch = provider.discover(request([{"name": "ICLR"}], [2023]))

    assert batch.coverage[0].state == "failed"
    assert batch.diagnostics[0].error_code == "source_unavailable"
    assert "OpenReview" in batch.diagnostics[0].message
    assert requested_paths(fixture_server.server) == []


# ------------------------------------------------------------------ USENIX

def usenix_node(path: str, title: str, *, pdf: bool = True, people: str = "", abstract: str = "") -> str:
    media = ('<span class="usenix-schedule-media pdf"><a href="' + path + '">pdf</a></span>'
             if pdf else "")
    return (f'<article class="node node-paper view-mode-schedule"><h2><a href="{path}">{title}</a></h2>'
            '<div class="content"><div class="field field-name-field-paper-people-text"><p>'
            f'{people}</p></div><div class="group-available-media">{media}</div>'
            f'<div class="field field-name-field-paper-description-long"><p>{abstract}</p></div>'
            '</div></article>')


USENIX_LISTING = "<html><body>" + "".join((
    usenix_node("/conference/atc24/presentation/wu-joint-keynote", "A Shared Keynote", pdf=False),
    usenix_node("/conference/osdi24/presentation/lovelace", "Verified Storage Tiering",
                people="Ada Lovelace and Alan Turing, <em>Analytical Engines;</em> Grace Hopper, "
                       "<em>Navy</em>", abstract="Tiers storage &amp; verifies it."),
    usenix_node("/conference/osdi24/presentation/hopper-panel", "A Panel", pdf=False),
)) + "</body></html>"


def usenix(fixture_server, **options) -> UsenixIndexProvider:
    return UsenixIndexProvider(fixture_server.client, origin=fixture_server.url("/").rstrip("/"),
                               production_hosts={fixture_server.host}, **options)


def test_usenix_reads_papers_with_a_pdf_from_the_technical_sessions_page(fixture_server) -> None:
    fixture_server.server.expect_request("/conference/osdi24/technical-sessions").respond_with_data(
        USENIX_LISTING, content_type="text/html")

    batch = usenix(fixture_server).discover(request([{"name": "OSDI"}], [2024]))

    (candidate,) = batch.candidates
    assert candidate.title == "Verified Storage Tiering"
    assert candidate.authors == ("Ada Lovelace", "Alan Turing", "Grace Hopper")
    assert candidate.abstract == "Tiers storage & verifies it."
    assert candidate.official_url == fixture_server.url("/conference/osdi24/presentation/lovelace")
    (coverage,) = batch.coverage
    assert (coverage.state, coverage.records_recognized, coverage.pages_fetched) == ("complete", 1, 1)
    # Paper pages are read only at acquisition, so the index costs one request per edition.
    assert requested_paths(fixture_server.server) == ["/conference/osdi24/technical-sessions"]


def test_usenix_waits_out_the_crawl_delay_between_editions(fixture_server) -> None:
    for edition in ("osdi23", "osdi24"):
        fixture_server.server.expect_request(f"/conference/{edition}/technical-sessions").respond_with_data(
            USENIX_LISTING.replace("osdi24", edition), content_type="text/html")
    now, pauses = [50.0], []

    def sleep(seconds: float) -> None:
        pauses.append(seconds)
        now[0] += seconds

    batch = usenix(fixture_server, sleeper=sleep, monotonic=lambda: now[0]).discover(
        request([{"name": "OSDI"}], [2023, 2024]))

    assert len(batch.candidates) == 2
    assert pauses == [10.0]
