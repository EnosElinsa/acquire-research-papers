from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from acquire_research_papers.discovery.contracts import (
    CandidateMetadata,
    DiscoveryBatch,
    DiscoveryCapabilities,
    DiscoveryDiagnostic,
    DiscoveryRequest,
)
from acquire_research_papers.http import SafeHttpClient


_PROVIDER_ID = "acl-anthology"
_OFFICIAL_VENUE = "Annual Meeting of the Association for Computational Linguistics"
_VENUE_ALIASES = frozenset(
    {
        "ACL",
        _OFFICIAL_VENUE,
        "Association for Computational Linguistics Annual Meeting",
    }
)
_LONG_ID = re.compile(r"^(?:19|20)\d{2}\.acl-long\.[1-9]\d*$", re.IGNORECASE)
_FULL_TYPES = frozenset({"full", "long", "regular", "research article", "research-article"})


def _split_values(value: str) -> tuple[str, ...]:
    return tuple(
        item.strip()
        for item in re.split(r"[;,]", value)
        if item.strip()
    )


class AclAnthologyDiscoveryProvider:
    def __init__(
        self,
        client: SafeHttpClient,
        *,
        event_template: str = "https://aclanthology.org/events/acl-{year}/",
        production_hosts: set[str] | frozenset[str] = frozenset({"aclanthology.org"}),
    ) -> None:
        self.client = client
        self.event_template = event_template
        self.production_hosts = frozenset(host.casefold() for host in production_hosts)

    def capabilities(self) -> DiscoveryCapabilities:
        return DiscoveryCapabilities(
            provider_id=_PROVIDER_ID,
            source_class="official_index",
            venue_aliases=_VENUE_ALIASES,
            evidence_fields=frozenset(
                {
                    "title",
                    "abstract",
                    "authors",
                    "venue",
                    "publication_type",
                    "doi",
                    "keywords",
                }
            ),
        )

    def _supports_request(self, request: DiscoveryRequest) -> bool:
        if request.venues and not any(
            self.capabilities().supports(venue) for venue in request.venues
        ):
            return False
        included = {value.casefold().replace("_", " ") for value in request.included_types}
        return not included or bool(included & _FULL_TYPES)

    @staticmethod
    def _candidate(article: Tag, year: int, event_url: str) -> CandidateMetadata | None:
        anthology_id = str(article.get("data-anthology-id", "")).strip()
        if not _LONG_ID.fullmatch(anthology_id):
            return None
        record_type = article.select_one(".type")
        if record_type and "front matter" in record_type.get_text(" ", strip=True).casefold():
            return None
        title_link = article.select_one("h5 a[href]")
        abstract_node = article.select_one(".abstract")
        title = title_link.get_text(" ", strip=True) if title_link else ""
        abstract = abstract_node.get_text(" ", strip=True) if abstract_node else ""
        if not title or not abstract:
            return None
        authors_node = article.select_one(".authors")
        authors = _split_values(authors_node.get_text(" ", strip=True)) if authors_node else ()
        keywords_node = article.select_one(".keywords")
        keywords = _split_values(keywords_node.get_text(" ", strip=True)) if keywords_node else ()
        evidence = ["title", "abstract", "venue", "publication_type", "doi"]
        if authors:
            evidence.append("authors")
        if keywords:
            evidence.append("keywords")
        source_fields = {field: (_PROVIDER_ID,) for field in evidence}
        return CandidateMetadata(
            key=anthology_id,
            title=title,
            year=year,
            venue=_OFFICIAL_VENUE,
            relevance_score=0.0,
            hard_gates_passed=True,
            evidence_fields=tuple(evidence),
            doi=f"10.18653/v1/{anthology_id}",
            official_url=urljoin(event_url, f"/{anthology_id}/"),
            authors=authors,
            abstract=abstract,
            keywords=keywords,
            publication_type="full",
            track="long",
            provenance={"source": _PROVIDER_ID, "event_url": event_url},
            field_provenance=source_fields,
        )

    def discover(self, request: DiscoveryRequest) -> DiscoveryBatch:
        if not self._supports_request(request):
            return DiscoveryBatch()
        candidates: list[CandidateMetadata] = []
        diagnostics: list[DiscoveryDiagnostic] = []
        covered: list[str] = []
        for year in request.years:
            event_url = self.event_template.format(year=year)
            host = urlsplit(event_url).hostname
            if not host or host.casefold() not in self.production_hosts:
                raise ValueError("ACL event URL is outside the configured host boundary")
            soup = BeautifulSoup(self.client.get(event_url).text, "html.parser")
            articles = soup.select("article[data-anthology-id]")
            if not articles:
                diagnostics.append(
                    DiscoveryDiagnostic(
                        provider_id=_PROVIDER_ID,
                        phase="event-index",
                        error_code="page_contract_changed",
                        message="ACL event index has no recognizable paper records",
                        venue=_OFFICIAL_VENUE,
                        year=year,
                        url=event_url,
                    )
                )
                continue
            covered.append(f"{_PROVIDER_ID}:{year}")
            for article in articles:
                candidate = self._candidate(article, year, event_url)
                if candidate is not None:
                    candidates.append(candidate)
        return DiscoveryBatch(
            candidates=tuple(candidates),
            diagnostics=tuple(diagnostics),
            covered_slices=tuple(covered),
        )
