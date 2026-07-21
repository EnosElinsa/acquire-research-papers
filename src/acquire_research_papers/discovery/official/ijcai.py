from __future__ import annotations

import re
import unicodedata
from datetime import date
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from acquire_research_papers.acquisition.adapters.ijcai import IjcaiProceedingsAdapter
from acquire_research_papers.acquisition.base import NotOfficial, PageContractChanged
from acquire_research_papers.discovery.contracts import (
    CandidateMetadata,
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


_PROVIDER_ID = "ijcai-proceedings"
_OFFICIAL_VENUE = "International Joint Conference on Artificial Intelligence"
_VENUE_ALIASES = frozenset(
    {
        "IJCAI",
        _OFFICIAL_VENUE,
        "International Joint Conferences on Artificial Intelligence",
    }
)
_MAIN_TYPES = frozenset(
    {
        "main",
        "full",
        "regular",
        "research article",
        "research-article",
        "proceedings article",
        "proceedings-article",
    }
)


def _normalized(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.findall(r"\w+", normalized))


def _split_values(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in re.split(r"[;,]", value) if item.strip())


def _meta_values(soup: BeautifulSoup, name: str) -> tuple[str, ...]:
    return tuple(
        str(tag.get("content", "")).strip()
        for tag in soup.find_all("meta", attrs={"name": re.compile(f"^{name}$", re.I)})
        if str(tag.get("content", "")).strip()
    )


def _publication_date(soup: BeautifulSoup, year: int) -> str | None:
    values = _meta_values(soup, "citation_publication_date")
    if len(values) != 1:
        return None
    parts = [int(value) for value in re.findall(r"\d+", values[0])[:3]]
    if not parts or parts[0] != year:
        return None
    while len(parts) < 3:
        parts.append(1)
    try:
        return date(*parts).isoformat()
    except ValueError:
        return None


def _abstract(soup: BeautifulSoup) -> str:
    labelled = soup.select_one("section#abstract, #abstract")
    if labelled is not None:
        return labelled.get_text(" ", strip=True)
    blocks = [
        node
        for node in soup.select("div.proceedings-detail > div.row > div.col-md-12")
        if node.select_one(".keywords") is None and node.get_text(" ", strip=True)
    ]
    if len(blocks) != 1:
        return ""
    return blocks[0].get_text(" ", strip=True)


def _keywords(soup: BeautifulSoup) -> tuple[str, ...]:
    metadata = _meta_values(soup, "keywords")
    if len(metadata) == 1:
        return _split_values(metadata[0])
    return tuple(
        node.get_text(" ", strip=True)
        for node in soup.select("div.proceedings-detail .keywords .topic")
        if node.get_text(" ", strip=True)
    )


def _content_soup(html: str) -> BeautifulSoup:
    # IJCAI abstracts occasionally contain raw mathematical comparisons such as
    # ``N<Nr``.  html.parser otherwise treats the variable after ``<`` as a tag
    # and truncates the evidence text (and may nest the keyword block inside it).
    escaped_comparisons = re.sub(r"<(?=[A-Z0-9])", "&lt;", html)
    return BeautifulSoup(escaped_comparisons, "html.parser")


def _requested_venue(request: DiscoveryRequest, year: int) -> str:
    if len(request.venues) == 1:
        return request.venues[0].name
    tokens = (str(year), str(year)[2:])
    for venue in request.venues:
        if any(
            re.search(rf"(?<!\d){re.escape(token)}(?!\d)", value)
            for token in tokens
            for value in venue.all_names
        ):
            return venue.name
    return _OFFICIAL_VENUE


class IjcaiDiscoveryProvider:
    def __init__(
        self,
        client: SafeHttpClient,
        *,
        index_template: str = "https://www.ijcai.org/proceedings/{year}/",
        production_hosts: set[str] | frozenset[str] = frozenset({"www.ijcai.org"}),
    ) -> None:
        self.client = client
        self.index_template = index_template
        self.production_hosts = frozenset(host.casefold() for host in production_hosts)
        self.detail_adapter = IjcaiProceedingsAdapter(
            client,
            production_hosts=self.production_hosts,
        )

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
                    "track",
                    "doi",
                    "keywords",
                    "publication_date",
                }
            ),
        )

    def _supports_request(self, request: DiscoveryRequest) -> bool:
        if request.venues and not any(
            self.capabilities().supports(venue) for venue in request.venues
        ):
            return False
        included = {value.casefold().replace("_", " ") for value in request.included_types}
        return not included or bool(included & _MAIN_TYPES)

    @staticmethod
    def _index_entries(soup: BeautifulSoup, year: int) -> list[tuple[str, str, str]]:
        entries: list[tuple[str, str, str]] = []
        track = ""
        expected_path = re.compile(rf"^/proceedings/{year}/\d+/?$")
        for node in soup.find_all(["h1", "h2", "h3", "h4", "div"]):
            if node.name in {"h1", "h2", "h3", "h4"}:
                heading = node.get_text(" ", strip=True)
                if "track" in heading.casefold():
                    track = heading
                continue
            classes = {str(value).casefold() for value in node.get("class", ())}
            if "paper_wrapper" not in classes:
                continue
            detail_anchors = [
                anchor
                for anchor in node.find_all("a", href=True)
                if expected_path.fullmatch(urlsplit(str(anchor.get("href", ""))).path)
            ]
            if len(detail_anchors) != 1:
                continue
            anchor = detail_anchors[0]
            href = str(anchor.get("href", "")).strip()
            title_node = node.select_one(".title")
            title = (
                title_node.get_text(" ", strip=True)
                if title_node is not None
                else anchor.get_text(" ", strip=True)
            )
            if title:
                entries.append((track, title, href))
        return entries

    @staticmethod
    def _matches_topic(title: str, request: DiscoveryRequest) -> bool:
        terms = tuple(_normalized(value) for value in request.queries if _normalized(value))
        normalized_title = _normalized(title)
        return not terms or any(term in normalized_title for term in terms)

    @staticmethod
    def _candidate(
        *,
        title: str,
        track: str,
        detail_url: str,
        detail_html: str,
        document,
        index_url: str,
        venue: str,
    ) -> CandidateMetadata:
        if _normalized(document.metadata.title) != _normalized(title):
            raise PageContractChanged("IJCAI index and detail titles disagree")
        if document.metadata.publication_type != "main" or "main track" not in track.casefold():
            raise PageContractChanged("IJCAI detail is outside the requested main track")
        soup = _content_soup(detail_html)
        abstract = _abstract(soup)
        if not abstract:
            raise PageContractChanged("IJCAI page has no abstract")
        keywords = _keywords(soup)
        publication_date = _publication_date(soup, document.metadata.year)
        evidence = [
            "title",
            "abstract",
            "authors",
            "venue",
            "publication_type",
            "track",
            "doi",
        ]
        if keywords:
            evidence.append("keywords")
        if publication_date:
            evidence.append("publication_date")
        return CandidateMetadata(
            key=document.metadata.doi or detail_url,
            title=document.metadata.title,
            year=document.metadata.year,
            venue=venue,
            relevance_score=0.0,
            hard_gates_passed=True,
            evidence_fields=tuple(evidence),
            doi=document.metadata.doi,
            official_url=detail_url,
            authors=document.metadata.authors,
            abstract=abstract,
            keywords=keywords,
            publication_type="main",
            track="Main Track",
            publication_date=publication_date,
            provenance={
                "source": _PROVIDER_ID,
                "index_url": index_url,
                "detail_url": detail_url,
            },
            field_provenance={field: (_PROVIDER_ID,) for field in evidence},
        )

    def discover(self, request: DiscoveryRequest) -> DiscoveryBatch:
        if not self._supports_request(request):
            return DiscoveryBatch()
        candidates: list[CandidateMetadata] = []
        diagnostics: list[DiscoveryDiagnostic] = []
        covered: list[str] = []
        for year in request.years:
            index_url = self.index_template.format(year=year)
            host = urlsplit(index_url).hostname
            if not host or host.casefold() not in self.production_hosts:
                raise ValueError("IJCAI index URL is outside the configured host boundary")
            try:
                index_html = self.client.get(index_url).text
            except (RateLimited, NetworkTransient):
                diagnostics.append(
                    DiscoveryDiagnostic(
                        provider_id=_PROVIDER_ID,
                        phase="proceedings-index",
                        error_code="network_transient",
                        message="IJCAI proceedings index is temporarily unavailable",
                        venue=_OFFICIAL_VENUE,
                        year=year,
                        url=index_url,
                        retryable=True,
                    )
                )
                continue
            except HttpStatusError:
                diagnostics.append(
                    DiscoveryDiagnostic(
                        provider_id=_PROVIDER_ID,
                        phase="proceedings-index",
                        error_code="source_unavailable",
                        message="IJCAI proceedings index is unavailable for the requested year",
                        venue=_OFFICIAL_VENUE,
                        year=year,
                        url=index_url,
                    )
                )
                continue
            soup = BeautifulSoup(index_html, "html.parser")
            entries = self._index_entries(soup, year)
            if not entries:
                diagnostics.append(
                    DiscoveryDiagnostic(
                        provider_id=_PROVIDER_ID,
                        phase="proceedings-index",
                        error_code="page_contract_changed",
                        message="IJCAI proceedings index has no recognizable paper records",
                        venue=_OFFICIAL_VENUE,
                        year=year,
                        url=index_url,
                    )
                )
                continue
            covered.append(f"{_PROVIDER_ID}:{year}:Main Track")
            requested_venue = _requested_venue(request, year)
            seen_urls: set[str] = set()
            for track, title, href in entries:
                if "main track" not in track.casefold() or not self._matches_topic(title, request):
                    continue
                detail_url = urljoin(index_url, href)
                if detail_url in seen_urls:
                    continue
                seen_urls.add(detail_url)
                try:
                    detail_html = self.client.get(detail_url).text
                    document = self.detail_adapter.parse(detail_url, detail_html)
                    candidate = self._candidate(
                        title=title,
                        track=track,
                        detail_url=detail_url,
                        detail_html=detail_html,
                        document=document,
                        index_url=index_url,
                        venue=requested_venue,
                    )
                except (RateLimited, NetworkTransient):
                    diagnostics.append(
                        DiscoveryDiagnostic(
                            provider_id=_PROVIDER_ID,
                            phase="paper-detail",
                            error_code="network_transient",
                            message="IJCAI paper detail is temporarily unavailable",
                            venue=_OFFICIAL_VENUE,
                            year=year,
                            url=detail_url,
                            retryable=True,
                        )
                    )
                    continue
                except (HttpStatusError, NotOfficial, PageContractChanged, ValueError):
                    diagnostics.append(
                        DiscoveryDiagnostic(
                            provider_id=_PROVIDER_ID,
                            phase="paper-detail",
                            error_code="page_contract_changed",
                            message="IJCAI paper detail does not match its expected structure",
                            venue=_OFFICIAL_VENUE,
                            year=year,
                            url=detail_url,
                        )
                    )
                    continue
                candidates.append(candidate)
        return DiscoveryBatch(
            candidates=tuple(candidates),
            diagnostics=tuple(diagnostics),
            covered_slices=tuple(covered),
        )
