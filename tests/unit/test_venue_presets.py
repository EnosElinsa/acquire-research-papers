from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from acquire_research_papers.discovery.contracts import DiscoveryRequest
from acquire_research_papers.discovery.venue_presets import PRESETS, apply_presets, find_preset
from acquire_research_papers.source_catalog import describe_sources
from acquire_research_papers.specs import SpecValidationError, load_corpus_spec


def spec(*venues: dict) -> dict:
    return {"mode": "corpus", "name": "presets", "target": {"minimum": 1, "maximum": 5},
            "scope": {"venues": list(venues), "years": {"include": [2024]}}}


def venue_of(value: dict) -> dict:
    (venue,) = apply_presets(value)["scope"]["venues"]
    return venue


def write(tmp_path: Path, value: dict) -> Path:
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_a_conference_short_name_receives_the_checked_openalex_series():
    venue = venue_of(spec({"name": "INFOCOM"}))

    assert venue["preset"] == "ieee-infocom"
    assert venue["openalex_source"] == ["S7407087743"]
    assert (venue["kind"], venue["publisher"], venue["short_name"]) == ("conference", "IEEE", "INFOCOM")
    assert "IEEE Conference on Computer Communications (INFOCOM)" in venue["aliases"]
    assert DiscoveryRequest.from_spec(apply_presets(spec({"name": "INFOCOM"}))).venues[0].preset == "ieee-infocom"


def test_a_journal_alias_receives_its_issn_and_matching_ignores_case_and_punctuation():
    venue = venue_of(spec({"name": "ieee tmc"}))

    assert (venue["preset"], venue["issn"], venue["kind"]) == ("ieee-tmc", ["1536-1233"], "journal")
    assert venue_of(spec({"name": "IEEE Communications Surveys and Tutorials"}))["preset"] == "ieee-comst"
    assert find_preset("IoT-J") is find_preset("iotj") is not None


def test_an_explicit_preset_applies_to_any_name_and_none_turns_matching_off():
    chosen = venue_of(spec({"name": "Main ICC track", "preset": "ieee-icc"}))
    assert (chosen["preset"], chosen["openalex_source"]) == ("ieee-icc", ["S4306419201"])

    off = venue_of(spec({"name": "INFOCOM", "preset": "none"}))
    assert off == {"name": "INFOCOM", "preset": "none"}


def test_the_venues_own_identifiers_a_different_publisher_or_two_matches_prevent_a_match():
    own = {"name": "INFOCOM", "openalex_source": ["S1"]}
    assert venue_of(spec(own)) == own
    other_publisher = {"name": "ICC", "publisher": "Springer"}
    assert venue_of(spec(other_publisher)) == other_publisher
    two = {"name": "TMC", "aliases": ["TWC"]}
    assert venue_of(spec(two)) == two


def test_an_unknown_preset_or_conflicting_identifiers_are_spec_errors(tmp_path: Path):
    with pytest.raises(SpecValidationError, match="unknown venue preset: ieee-nope"):
        load_corpus_spec(write(tmp_path, spec({"name": "X", "preset": "ieee-nope"})))
    conflicting = spec({"name": "INFOCOM", "preset": "ieee-infocom", "openalex_source": ["S1"]})
    with pytest.raises(SpecValidationError, match="conflicts with the venue's own identifiers"):
        load_corpus_spec(write(tmp_path, conflicting))


def test_an_expanded_spec_such_as_a_copied_request_spec_loads_unchanged(tmp_path: Path):
    expanded = load_corpus_spec(write(tmp_path, spec({"name": "INFOCOM"}, {"name": "IEEE TWC"})))

    assert load_corpus_spec(write(tmp_path, expanded)) == expanded
    assert [venue["preset"] for venue in expanded["scope"]["venues"]] == ["ieee-infocom", "ieee-twc"]


def test_sources_lists_the_presets_and_shows_which_one_each_slice_uses(tmp_path: Path):
    result = describe_sources(load_corpus_spec(write(tmp_path, spec({"name": "INFOCOM"}))))

    (slice_,) = result["requested_slices"]
    assert slice_["preset"] == "ieee-infocom"
    assert slice_["openalex_venue"]["sources"] == ["S7407087743"]
    assert slice_["crossref"]["diagnostic"] == "enumerated_by_openalex_source"
    listed = {preset["id"]: preset for preset in result["venue_presets"]}
    assert listed["ieee-tmc"]["issn"] == ["1536-1233"]
    assert listed["ieee-infocom"]["checked"].startswith("OpenAlex S7407087743")


def test_every_preset_identifier_is_well_formed_and_accepted_by_the_schema(tmp_path: Path):
    for preset in PRESETS:
        assert preset.issn or preset.openalex_source or preset.collection_doi, preset.id
        assert all(re.fullmatch(r"\d{4}-\d{3}[\dX]", value) for value in preset.issn), preset.id
        assert all(re.fullmatch(r"S\d{1,15}", value) for value in preset.openalex_source), preset.id
        assert all(re.fullmatch(r"10\.\d{4,9}/\S+", value) for value in preset.collection_doi), \
            preset.id
        assert preset.checked, preset.id
    venues = [{"name": preset.short_name, "preset": preset.id} for preset in PRESETS]
    loaded = load_corpus_spec(write(tmp_path, spec(*venues)))
    assert [venue["preset"] for venue in loaded["scope"]["venues"]] == [preset.id for preset in PRESETS]


def test_renamed_and_per_edition_presets_carry_every_identifier():
    ton = venue_of(spec({"name": "IEEE Transactions on Networking"}))
    assert (ton["preset"], ton["issn"]) == ("ieee-ton", ["1063-6692", "2998-4157"])

    mobicom = venue_of(spec({"name": "MobiCom"}))
    assert mobicom["preset"] == "acm-mobicom" and mobicom["publisher"] == "ACM"
    assert "10.1145/3636534" in mobicom["collection_doi"]  # the 2024 edition
    request = DiscoveryRequest.from_spec(apply_presets(spec({"name": "MobiCom"})))
    assert request.venues[0].collection_doi == tuple(mobicom["collection_doi"])


def test_crossref_receives_every_issn_of_a_venue_in_one_request():
    from acquire_research_papers.discovery.contracts import CandidatePage
    from acquire_research_papers.discovery.providers import CrossrefVenueDiscoveryProvider

    seen = []

    def searcher(query, **kwargs):
        seen.append(kwargs["filters"])
        return CandidatePage(())

    request = DiscoveryRequest.from_spec(apply_presets(spec({"name": "IEEE ToN"})))
    batch = CrossrefVenueDiscoveryProvider(searcher).discover(request)

    assert seen[0]["issn"] == ("1063-6692", "2998-4157")
    assert batch.coverage[0].state == "complete"


def test_the_crossref_client_repeats_a_filter_for_each_value():
    from urllib.parse import parse_qs, urlsplit

    import httpx

    from acquire_research_papers.discovery.crossref import CrossrefClient
    from acquire_research_papers.http import SafeHttpClient

    urls = []

    def handler(http_request: httpx.Request) -> httpx.Response:
        urls.append(str(http_request.url))
        return httpx.Response(200, json={"message": {"items": [], "total-results": 0}})

    client = SafeHttpClient(allowed_hosts={"api.crossref.org"})
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    CrossrefClient(client=client).search("", filters={"issn": ("1063-6692", "2998-4157"),
                                                      "from-pub-date": "2025-01-01"})

    (value,) = parse_qs(urlsplit(urls[0]).query)["filter"]
    assert value == "from-pub-date:2025-01-01,issn:1063-6692,issn:2998-4157"


@pytest.mark.parametrize(("name", "preset_id", "issns"), [
    ("T-RO", "ieee-tro", ["1552-3098", "1941-0468"]),
    ("IEEE RA-L", "ieee-ral", ["2377-3766"]),
    ("IEEE/ASME Transactions on Mechatronics", "ieee-tmech", ["1083-4435", "1941-014X"]),
    ("TIE", "ieee-tie", ["0278-0046", "1557-9948"]),
    ("IEEE TIM", "ieee-tim", ["0018-9456", "1557-9662"]),
    ("IEEE/CAA JAS", "ieee-jas", ["2329-9266", "2329-9274"]),
    ("IEEE Robotics and Automation Magazine", "ieee-ram", ["1070-9932", "1558-223X"]),
    ("TCST", "ieee-tcst", ["1063-6536", "1558-0865"]),
    ("TCDS", "ieee-tcds", ["2379-8920", "2379-8939"]),
])
def test_robotics_journals_receive_their_print_and_electronic_issns(name, preset_id, issns):
    venue = venue_of(spec({"name": name}))

    assert (venue["preset"], venue["issn"]) == (preset_id, issns)
    assert find_preset(preset_id).checked.startswith("Crossref ISSN")
