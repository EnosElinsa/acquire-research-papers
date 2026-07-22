from __future__ import annotations

import re
from dataclasses import replace
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from acquire_research_papers.discovery.contracts import (
    CandidateMetadata,
    CoverageSlice,
    DiscoveryBatch,
    DiscoveryCapabilities,
    DiscoveryDiagnostic,
    DiscoveryRequest,
)
from acquire_research_papers.http import (
    HttpStatusError,
    NetworkTransient,
    RateLimited,
    SafeHttpClient,
)


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
_FULL_TYPES = frozenset(
    {
        "full",
        "long",
        "regular",
        "research article",
        "research-article",
        "proceedings article",
        "proceedings-article",
    }
)


def _split_values(value: str) -> tuple[str, ...]:
    return tuple(
        item.strip()
        for item in re.split(r"[;,]", value)
        if item.strip()
    )


def _clean_fragments(fragments: list[str], *, preserve_boundaries: bool = False) -> str:
    joined = "".join(fragments) if preserve_boundaries else " ".join(fragments)
    return " ".join(joined.split())


def _requested_venue(request: DiscoveryRequest, year: int) -> str:
    eligible = tuple(venue for venue in request.venues if venue.supports_year(year))
    if len(eligible) == 1:
        return eligible[0].name
    tokens = (str(year), str(year)[2:])
    for venue in eligible or request.venues:
        if any(
            re.search(rf"(?<!\d){re.escape(token)}(?!\d)", value)
            for token in tokens
            for value in venue.all_names
        ):
            return venue.name
    return _OFFICIAL_VENUE


class _AclVolumeParser(HTMLParser):
    """Extract only long-paper evidence without materializing a multi-megabyte DOM."""

    def __init__(self, year: int) -> None:
        super().__init__(convert_charrefs=True)
        self.year = year
        self._landing_path = re.compile(rf"^/{year}\.acl-long\.[1-9]\d*/$")
        self.order: list[str] = []
        self.records: dict[str, dict[str, object]] = {}
        self.current_id = ""
        self.title_id = ""
        self.title_fragments: list[str] = []
        self.author_id = ""
        self.author_fragments: list[str] = []
        self.abstract_id = ""
        self.abstract_depth = 0
        self.abstract_fragments: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "a":
            href = str(attributes.get("href") or "")
            path = urlsplit(href).path
            if self._landing_path.fullmatch(path):
                anthology_id = path.strip("/")
                if anthology_id not in self.records:
                    self.records[anthology_id] = {"title": "", "authors": [], "abstract": ""}
                    self.order.append(anthology_id)
                self.current_id = anthology_id
                self.title_id = anthology_id
                self.title_fragments = []
            elif self.current_id and path.startswith("/people/"):
                self.author_id = self.current_id
                self.author_fragments = []
        if tag == "div":
            if self.abstract_id:
                self.abstract_depth += 1
                return
            identifier = str(attributes.get("id") or "")
            match = re.fullmatch(rf"abstract-{self.year}--acl-long--([1-9]\d*)", identifier)
            if match:
                self.abstract_id = f"{self.year}.acl-long.{match.group(1)}"
                self.abstract_depth = 1
                self.abstract_fragments = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.title_id:
            self.records[self.title_id]["title"] = _clean_fragments(
                self.title_fragments,
                preserve_boundaries=True,
            )
            self.title_id = ""
            self.title_fragments = []
        elif tag == "a" and self.author_id:
            author = _clean_fragments(self.author_fragments, preserve_boundaries=True)
            if author:
                authors = self.records[self.author_id]["authors"]
                assert isinstance(authors, list)
                authors.append(author)
            self.author_id = ""
            self.author_fragments = []
        if tag == "div" and self.abstract_id:
            self.abstract_depth -= 1
            if self.abstract_depth == 0:
                if self.abstract_id in self.records:
                    self.records[self.abstract_id]["abstract"] = _clean_fragments(
                        self.abstract_fragments
                    )
                self.abstract_id = ""
                self.abstract_fragments = []

    def handle_data(self, data: str) -> None:
        if self.title_id:
            self.title_fragments.append(data)
        elif self.author_id:
            self.author_fragments.append(data)
        if self.abstract_id:
            self.abstract_fragments.append(data)


class AclAnthologyDiscoveryProvider:
    def __init__(
        self,
        client: SafeHttpClient,
        *,
        event_template: str = "https://aclanthology.org/volumes/{year}.acl-long/",
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
    def _build_candidate(
        *,
        anthology_id: str,
        title: str,
        abstract: str,
        authors: tuple[str, ...],
        keywords: tuple[str, ...],
        year: int,
        event_url: str,
    ) -> CandidateMetadata | None:
        if not title:
            return None
        evidence = ["title", "venue", "publication_type", "doi"]
        if abstract:
            evidence.append("abstract")
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

    @classmethod
    def _article_candidate(
        cls,
        article: Tag,
        year: int,
        event_url: str,
    ) -> CandidateMetadata | None:
        anthology_id = str(article.get("data-anthology-id", "")).strip()
        if not _LONG_ID.fullmatch(anthology_id):
            return None
        record_type = article.select_one(".type")
        if record_type and "front matter" in record_type.get_text(" ", strip=True).casefold():
            return None
        title_link = article.select_one("h5 a[href]")
        abstract_node = article.select_one(".abstract")
        authors_node = article.select_one(".authors")
        keywords_node = article.select_one(".keywords")
        return cls._build_candidate(
            anthology_id=anthology_id,
            title=title_link.get_text(" ", strip=True) if title_link else "",
            abstract=abstract_node.get_text(" ", strip=True) if abstract_node else "",
            authors=(
                _split_values(authors_node.get_text(" ", strip=True)) if authors_node else ()
            ),
            keywords=(
                _split_values(keywords_node.get_text(" ", strip=True))
                if keywords_node
                else ()
            ),
            year=year,
            event_url=event_url,
        )

    @classmethod
    def _volume_candidates(
        cls,
        html: str,
        year: int,
        event_url: str,
    ) -> tuple[int, list[CandidateMetadata]]:
        parser = _AclVolumeParser(year)
        parser.feed(html)
        parser.close()
        candidates: list[CandidateMetadata] = []
        for anthology_id in parser.order:
            record = parser.records[anthology_id]
            raw_authors = record["authors"]
            assert isinstance(raw_authors, list)
            candidate = cls._build_candidate(
                anthology_id=anthology_id,
                title=str(record["title"]),
                abstract=str(record["abstract"]),
                authors=tuple(str(author) for author in raw_authors),
                keywords=(),
                year=year,
                event_url=event_url,
            )
            if candidate is not None:
                candidates.append(candidate)
        return len(parser.order), candidates

    def discover(self, request: DiscoveryRequest) -> DiscoveryBatch:
        if not self._supports_request(request):
            return DiscoveryBatch()
        candidates: list[CandidateMetadata] = []
        diagnostics: list[DiscoveryDiagnostic] = []
        covered: list[str] = []
        coverage: list[CoverageSlice] = []
        for year in request.years:
            if request.venues and not any(
                venue.supports_year(year) for venue in request.venues
            ):
                continue
            if f"{_PROVIDER_ID}:{year}" in request.completed_slices:
                continue
            event_url = self.event_template.format(year=year)
            host = urlsplit(event_url).hostname
            if not host or host.casefold() not in self.production_hosts:
                raise ValueError("ACL event URL is outside the configured host boundary")
            try:
                html = self.client.get(event_url).text
            except (RateLimited, NetworkTransient):
                diagnostics.append(
                    DiscoveryDiagnostic(
                        provider_id=_PROVIDER_ID,
                        phase="event-index",
                        error_code="network_transient",
                        message="ACL volume index is temporarily unavailable",
                        venue=_OFFICIAL_VENUE,
                        year=year,
                        url=event_url,
                        retryable=True,
                    )
                )
                coverage.append(
                    CoverageSlice(
                        provider_id=_PROVIDER_ID,
                        venue=_OFFICIAL_VENUE,
                        year=year,
                        state="failed",
                        diagnostic_code="network_transient",
                    )
                )
                continue
            except HttpStatusError:
                diagnostics.append(
                    DiscoveryDiagnostic(
                        provider_id=_PROVIDER_ID,
                        phase="event-index",
                        error_code="source_unavailable",
                        message="ACL volume index is unavailable for the requested year",
                        venue=_OFFICIAL_VENUE,
                        year=year,
                        url=event_url,
                    )
                )
                coverage.append(
                    CoverageSlice(
                        provider_id=_PROVIDER_ID,
                        venue=_OFFICIAL_VENUE,
                        year=year,
                        state="failed",
                        diagnostic_code="source_unavailable",
                    )
                )
                continue
            if "data-anthology-id" in html:
                soup = BeautifulSoup(html, "html.parser")
                articles = soup.select("article[data-anthology-id]")
                recognized = len(articles)
                year_candidates = [
                    candidate
                    for article in articles
                    if (candidate := self._article_candidate(article, year, event_url)) is not None
                ]
            else:
                recognized, year_candidates = self._volume_candidates(html, year, event_url)
            if not recognized:
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
                coverage.append(
                    CoverageSlice(
                        provider_id=_PROVIDER_ID,
                        venue=_OFFICIAL_VENUE,
                        year=year,
                        state="failed",
                        pages_fetched=1,
                        diagnostic_code="page_contract_changed",
                    )
                )
                continue
            covered.append(f"{_PROVIDER_ID}:{year}")
            requested_venue = _requested_venue(request, year)
            for candidate in year_candidates:
                candidates.append(replace(candidate, venue=requested_venue))
            coverage.append(
                CoverageSlice(
                    provider_id=_PROVIDER_ID,
                    venue=requested_venue,
                    year=year,
                    state="complete",
                    pages_fetched=1,
                    records_fetched=len(year_candidates),
                )
            )
        return DiscoveryBatch(
            candidates=tuple(candidates),
            diagnostics=tuple(diagnostics),
            covered_slices=tuple(covered),
            coverage=tuple(coverage),
        )
