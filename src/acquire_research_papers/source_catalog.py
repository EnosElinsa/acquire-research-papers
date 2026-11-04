"""Offline source capabilities; live coverage remains a property of each run."""
from __future__ import annotations

from acquire_research_papers.discovery.contracts import DiscoveryRequest
from acquire_research_papers.discovery.official.acl import AclAnthologyDiscoveryProvider
from acquire_research_papers.discovery.official.archives import ARCHIVE_INDEX_PROVIDERS
from acquire_research_papers.discovery.official.ijcai import IjcaiDiscoveryProvider
from acquire_research_papers.discovery.providers import crossref_scope

_LEGACY_SCOPES = {"acl-anthology": "ACL long papers", "ijcai-proceedings": "IJCAI main track"}


def _scope(provider) -> str:
    return getattr(provider, "scope_description", "") or _LEGACY_SCOPES[
        provider.capabilities().provider_id]


def describe_sources(spec: dict | None = None) -> dict:
    providers = [AclAnthologyDiscoveryProvider(None), IjcaiDiscoveryProvider(None),
                 *(provider(None) for provider in ARCHIVE_INDEX_PROVIDERS)]
    sources = [
        {"id": provider.capabilities().provider_id, "role": "official_index",
         "venue_aliases": sorted(provider.capabilities().venue_aliases),
         "scope": _scope(provider), "credentials": False}
        for provider in providers
    ]
    sources.extend([
        {"id": "crossref", "role": "metadata_venue_enumerator", "credentials": False,
         "scope": "deposited records; exact identifiers preferred"},
        {"id": "openalex", "role": "optional_search_and_enrichment", "credentials": "optional API configuration"},
        {"id": "semantic-scholar", "role": "optional_search_and_enrichment", "credentials": "optional API configuration"},
        {"id": "orcid", "role": "author_bibliography", "credentials": False},
        {"id": "dblp", "role": "author_bibliography", "credentials": False},
        {"id": "author-homepage", "role": "author_bibliography", "credentials": False},
        {"id": "elsevier", "role": "expected_identity_metadata", "credentials": "Elsevier API key; entitlement separate"},
    ])
    acquisition = {"ACL": "official_pair", "IJCAI": "official_pair", "IEEE": "official_pair_institution_access",
                   "ACM": "official_pair_access_dependent", "Elsevier": "manual_only",
                   "ScienceDirect": "manual_only", "AAAI": "official_pair",
                   "NeurIPS": "official_pair", "PMLR": "official_pair_page_embedded_bibtex",
                   "CVF": "open_access_version_page_embedded_bibtex",
                   "Springer": "official_pair_open_access_or_entitled_network"}
    slices = []
    if spec is not None:
        request = DiscoveryRequest.from_spec(spec)
        for venue in request.venues:
            for year in request.years:
                if not venue.supports_year(year):
                    continue
                scoped = request.with_scope((venue,), (year,))
                official = [provider for provider in providers
                            if provider.capabilities().supports(venue)
                            and provider.capabilities().supports_year(year)
                            and provider._supports_request(scoped)]
                artifact_support = acquisition.get(venue.publisher, "unknown")
                if official and artifact_support == "unknown":
                    artifact_support = getattr(official[0], "acquisition", "official_pair")
                slices.append({"venue": venue.name, "year": year, "publisher": venue.publisher,
                               "official_indexes": [provider.capabilities().provider_id
                                                    for provider in official],
                               "crossref": crossref_scope(venue),
                               "acquisition": artifact_support, "observed_coverage": None})
    return {"schema_version": 1, "status": "capabilities_only", "sources": sources,
            "artifact_acquisition": acquisition, "requested_slices": slices,
            "universal_completeness": False, "priority_venues": [],
            "coverage_note": "No network checks performed. Complete enumeration means completion within one source and scope; upstream omissions remain possible. See coverage.jsonl and discovery-errors.jsonl in an actual run.",
            "next_action": "Choose priority venues and verify official venue/year indexes against observed run coverage."}
