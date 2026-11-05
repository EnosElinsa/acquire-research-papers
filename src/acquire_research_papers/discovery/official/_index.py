"""Shared machinery for official venue indexes that list papers on the venue's own archive.

A provider maps a requested venue to an archive code, enumerates one venue-year slice, and
fetches per-paper pages with bounded concurrency. Paper pages already read in an earlier
partial run are reused from the seed candidates, so resuming a large slice is cheap.
"""
from __future__ import annotations

import re
import threading
import unicodedata
from collections import Counter
from collections.abc import Callable, Mapping
from typing import TypeVar
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from acquire_research_papers.acquisition.base import NotOfficial, PageContractChanged
from acquire_research_papers.discovery.contracts import (
    CandidateMetadata,
    CoverageSlice,
    DiscoveryBatch,
    DiscoveryCapabilities,
    DiscoveryDiagnostic,
    DiscoveryRequest,
    VenueScope,
)
from acquire_research_papers.http import (
    HttpStatusError,
    NetworkTransient,
    RateLimited,
    SafeHttpClient,
)

_RETRYABLE = frozenset({"network_transient", "rate_limited"})
_Item = TypeVar("_Item")
_DATE = re.compile(r"((?:19|20)\d{2})-(\d{2})-(\d{2})")


def normalized_title(value: str) -> str:
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", value).casefold()))


def iso_date(value: str | None) -> str | None:
    match = _DATE.search(value or "")
    return "-".join(match.groups()) if match else None


def type_key(value: str) -> str:
    """The corpus screen's publication-type normalization ("main" and "full" are articles)."""
    normalized = " ".join(re.findall(r"\w+", value.casefold()))
    return "proceedings article" if normalized in {"full", "main"} else normalized


class SliceUnavailable(Exception):
    """The archive publishes no index for the requested venue and year."""


@dataclass
class SliceResult:
    candidates: list[CandidateMetadata] = field(default_factory=list)
    recognized: int = 0
    pages_fetched: int = 0
    issues: Counter = field(default_factory=Counter)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def fetched(self, count: int = 1) -> None:
        with self._lock:
            self.pages_fetched += count

    def issue(self, phase: str, code: str, count: int = 1) -> None:
        with self._lock:
            self.issues[(phase, code)] += count


def _failure_code(error: BaseException) -> str:
    if isinstance(error, RateLimited):
        return "rate_limited"
    if isinstance(error, NetworkTransient):
        return "network_transient"
    if isinstance(error, HttpStatusError) and error.status_code >= 500:
        return "network_transient"
    return "page_contract_changed"


class OfficialIndexProvider:
    provider_id = ""
    label = ""
    scope_description = ""
    acquisition = "official_pair"
    # Display alias -> archive code. Matching is case-insensitive.
    venue_aliases: Mapping[str, str] = {}
    evidence_fields = frozenset({"title", "abstract", "authors", "venue", "publication_type"})
    # Normalized publication types this archive's papers carry (see ``type_key``).
    publication_types = frozenset({"proceedings article"})
    # Declared venue publishers (casefolded) this archive serves.
    publishers: frozenset[str] = frozenset()

    def __init__(
        self,
        client: SafeHttpClient | None,
        *,
        production_hosts: set[str] | frozenset[str],
        workers: int = 4,
    ) -> None:
        self.client = client
        self.production_hosts = frozenset(host.casefold().rstrip(".") for host in production_hosts)
        self.workers = max(1, workers)

    def capabilities(self) -> DiscoveryCapabilities:
        return DiscoveryCapabilities(
            provider_id=self.provider_id,
            source_class="official_index",
            venue_aliases=frozenset(self.venue_aliases),
            evidence_fields=frozenset(self.evidence_fields),
        )

    def code_for(self, venue: VenueScope) -> str | None:
        names = {name.casefold() for name in (*venue.all_names, venue.short_name) if name}
        for alias, code in self.venue_aliases.items():
            if alias.casefold() in names:
                return code
        return None

    def accepts_venue(self, venue: VenueScope) -> bool:
        # A different declared publisher (for example ``IEEE`` for CVPR) keeps that route.
        publisher = venue.publisher.strip().casefold()
        return self.code_for(venue) is not None and (not publisher or publisher in self.publishers)

    def _supports_request(self, request: DiscoveryRequest) -> bool:
        if request.venues and not any(self.accepts_venue(venue) for venue in request.venues):
            return False
        included = {type_key(value) for value in request.included_types}
        return not included or bool(included & self.publication_types)

    @staticmethod
    def wants_type(publication_type: str, request: DiscoveryRequest) -> bool:
        """Skip reading papers the corpus screen would reject on publication type anyway."""
        key = type_key(publication_type)
        included = {type_key(value) for value in request.included_types}
        excluded = {type_key(value) for value in request.excluded_types}
        return (not included or key in included) and key not in excluded

    def require_host(self, url: str) -> None:
        host = (urlsplit(url).hostname or "").casefold().rstrip(".")
        if host not in self.production_hosts:
            raise NotOfficial(f"{self.label} URL is outside the archive host")

    def get_text(self, url: str, result: SliceResult) -> str:
        self.require_host(url)
        if self.client is None:
            raise RuntimeError(f"{self.label} index client is not configured")
        text = self.client.get(url).text
        result.fetched()
        return text

    def collect(
        self,
        archive: str,
        year: int,
        venue: VenueScope,
        request: DiscoveryRequest,
        seeds: Mapping[str, CandidateMetadata],
        result: SliceResult,
    ) -> str:
        """Fill ``result`` for one slice and return the index URL used."""
        raise NotImplementedError

    def fetch_details(
        self,
        items: list[_Item],
        fetch_one: Callable[[_Item], CandidateMetadata],
        result: SliceResult,
        *,
        phase: str = "paper-detail",
    ) -> None:
        """Run ``fetch_one`` over ``items`` with bounded concurrency, keeping index order."""
        stop = threading.Event()

        def run(item: _Item) -> tuple[CandidateMetadata | None, str]:
            if stop.is_set():
                return None, "rate_limited"
            try:
                return fetch_one(item), ""
            # Page drift can surface as a missing node (AttributeError/KeyError/TypeError);
            # it costs one paper, never the whole slice.
            except (RateLimited, NetworkTransient, HttpStatusError, PageContractChanged,
                    NotOfficial, ValueError, AttributeError, KeyError, TypeError) as error:
                code = _failure_code(error)
                if code == "rate_limited":
                    stop.set()
                return None, code

        if not items:
            return
        with ThreadPoolExecutor(max_workers=min(self.workers, len(items))) as pool:
            outcomes = list(pool.map(run, items))
        for candidate, code in outcomes:
            if candidate is not None:
                result.candidates.append(candidate)
            else:
                result.issue(phase, code)

    def candidate(
        self,
        *,
        title: str,
        year: int,
        venue: VenueScope,
        url: str,
        index_url: str,
        authors: tuple[str, ...] = (),
        abstract: str = "",
        doi: str | None = None,
        publication_type: str = "proceedings-article",
        track: str | None = None,
        publication_date: str | None = None,
    ) -> CandidateMetadata:
        if not title:
            raise PageContractChanged(f"{self.label} paper has no title")
        evidence = ["title", "venue", "publication_type"]
        for name, value in (("authors", authors), ("abstract", abstract), ("doi", doi),
                            ("track", track), ("publication_date", publication_date)):
            if value:
                evidence.append(name)
        return CandidateMetadata(
            key=doi or url,
            title=title,
            year=year,
            venue=venue.name,
            relevance_score=0.0,
            hard_gates_passed=True,
            evidence_fields=tuple(evidence),
            doi=doi,
            official_url=url,
            authors=authors,
            abstract=abstract,
            publication_type=publication_type,
            track=track,
            publication_date=publication_date,
            provenance={"source": self.provider_id, "index_url": index_url, "detail_url": url},
            field_provenance={name: (self.provider_id,) for name in evidence},
        )

    def _diagnostic(self, phase: str, code: str, message: str, venue: str, year: int,
                    url: str = "") -> DiscoveryDiagnostic:
        return DiscoveryDiagnostic(
            provider_id=self.provider_id, phase=phase, error_code=code, message=message,
            venue=venue, year=year, url=url, retryable=code in _RETRYABLE,
        )

    def _issue_message(self, phase: str, code: str, count: int) -> str:
        what = "paper pages" if phase == "paper-detail" else "index records"
        if code == "rate_limited":
            return f"{self.label} rate-limited requests; {count} {what} were not read"
        if code == "network_transient":
            return f"{count} {self.label} {what} were temporarily unavailable"
        return f"{count} {self.label} {what} did not match their expected structure"

    def discover(self, request: DiscoveryRequest) -> DiscoveryBatch:
        candidates: list[CandidateMetadata] = []
        diagnostics: list[DiscoveryDiagnostic] = []
        coverage: list[CoverageSlice] = []
        seeds = {
            candidate.official_url: candidate
            for candidate in request.seed_candidates
            if candidate.official_url and candidate.abstract
            and candidate.provenance.get("source") == self.provider_id
        }
        if not self._supports_request(request):
            return DiscoveryBatch()
        for venue in request.venues:
            archive = self.code_for(venue)
            if archive is None:
                continue
            for year in request.years:
                if not venue.supports_year(year):
                    continue
                if f"{self.provider_id}:{venue.name}:{year}" in request.completed_slices:
                    continue
                result = SliceResult()
                index_url = ""
                failure: tuple[str, str] | None = None
                try:
                    index_url = self.collect(archive, year, venue, request, seeds, result)
                except SliceUnavailable as exc:
                    failure = ("source_unavailable", str(exc))
                except (RateLimited, NetworkTransient) as exc:
                    failure = (_failure_code(exc), f"{self.label} index is temporarily unavailable")
                except HttpStatusError as exc:
                    if exc.status_code in {404, 410}:
                        failure = ("source_unavailable",
                                   f"{self.label} has no index for {venue.name} {year}")
                    else:
                        failure = (_failure_code(exc),
                                   f"{self.label} index returned HTTP {exc.status_code}")
                except (PageContractChanged, NotOfficial, ValueError) as exc:
                    failure = ("page_contract_changed", str(exc) or
                               f"{self.label} index does not match its expected structure")
                if failure is None and not result.recognized:
                    failure = ("page_contract_changed",
                               f"{self.label} index has no recognizable paper records")
                candidates.extend(result.candidates)
                if failure is not None:
                    diagnostics.append(self._diagnostic("proceedings-index", failure[0],
                                                        failure[1], venue.name, year, index_url))
                    state, diagnostic_code = ("partial" if result.candidates else "failed"), failure[0]
                else:
                    for (phase, issue_code), count in sorted(result.issues.items()):
                        diagnostics.append(self._diagnostic(
                            phase, issue_code, self._issue_message(phase, issue_code, count),
                            venue.name, year, index_url))
                    state = "partial" if result.issues else "complete"
                    diagnostic_code = (min(code for _, code in result.issues)
                                       if result.issues else "")
                coverage.append(CoverageSlice(
                    provider_id=self.provider_id, venue=venue.name, year=year, state=state,
                    pages_fetched=result.pages_fetched, records_fetched=len(result.candidates),
                    diagnostic_code=diagnostic_code, records_recognized=result.recognized,
                ))
        return DiscoveryBatch(candidates=tuple(candidates), diagnostics=tuple(diagnostics),
                              coverage=tuple(coverage))
