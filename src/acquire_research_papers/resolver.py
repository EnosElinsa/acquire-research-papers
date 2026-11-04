from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote, urljoin, urlsplit

import httpx

from acquire_research_papers import __version__
from acquire_research_papers.acquisition.base import AcquiredPair, SourceAdapter, SourceDocument
from acquire_research_papers.acquisition.router import AdapterRouter, canonical_landing_url
from acquire_research_papers.http import NetworkTransient, RateLimited
from acquire_research_papers.models import normalize_doi


class AmbiguousInput(ValueError):
    """An input cannot be mapped to exactly one supported official record."""


class UnsupportedPublisher(AmbiguousInput):
    """The official landing page is on a host without an acquisition adapter."""

    def __init__(self, hostname: str) -> None:
        super().__init__(
            "URL does not match a supported official publisher adapter: "
            f"{hostname}; download the official pair manually"
        )
        self.hostname = hostname


_DOI = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
_DOI_HOSTS = frozenset({"doi.org", "dx.doi.org", "www.doi.org"})
_REDIRECTS = frozenset({301, 302, 303, 307, 308})


class DoiRedirectResolver:
    def __init__(
        self,
        endpoint: str = "https://doi.org/",
        timeout: float = 20.0,
        *,
        retries: int = 3,
        backoff_seconds: float = 1.0,
        max_hops: int = 3,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.endpoint = endpoint.rstrip("/") + "/"
        self.timeout = timeout
        self.retries = retries
        self.backoff_seconds = backoff_seconds
        self.max_hops = max_hops
        self._sleeper = sleeper

    def _get(self, client: httpx.Client, url: str) -> httpx.Response:
        for attempt in range(self.retries + 1):
            try:
                response = client.get(url, headers={"Accept": "text/html"})
            except httpx.TransportError as exc:
                if attempt == self.retries:
                    raise NetworkTransient("DOI resolver network retries exhausted") from exc
                self._sleeper(self.backoff_seconds * (2**attempt))
                continue
            if response.status_code == 429:
                raise RateLimited(
                    429, url, retry_after_seconds=response.headers.get("Retry-After")
                )
            if response.status_code >= 500:
                if attempt == self.retries:
                    raise NetworkTransient(
                        f"DOI resolver returned HTTP {response.status_code} after retries"
                    )
                self._sleeper(self.backoff_seconds * (2**attempt))
                continue
            return response
        raise AssertionError("DOI resolver retry loop escaped its bound")

    def resolve(self, doi: str) -> str:
        normalized = normalize_doi(doi)
        if not normalized or not _DOI.fullmatch(normalized):
            raise AmbiguousInput("input is not a valid DOI")
        url = urljoin(self.endpoint, quote(normalized, safe="/"))
        with httpx.Client(
            follow_redirects=False,
            timeout=self.timeout,
            headers={"User-Agent": f"acquire-research-papers/{__version__}"},
        ) as client:
            for _hop in range(self.max_hops):
                response = self._get(client, url)
                if response.status_code not in _REDIRECTS:
                    raise AmbiguousInput(f"DOI resolver returned HTTP {response.status_code}")
                location = response.headers.get("Location")
                target = urljoin(str(response.url), location or "")
                parsed = urlsplit(target)
                if not location or parsed.scheme not in {"http", "https"} or not parsed.hostname:
                    raise AmbiguousInput("DOI resolver returned an unsafe redirect")
                if parsed.hostname.casefold().rstrip(".") not in _DOI_HOSTS:
                    return target
                # A DOI alias redirects to another DOI; follow only DOI-resolver hops.
                url = target
        raise AmbiguousInput("DOI resolver redirected too many times")


@dataclass(frozen=True)
class ResolvedSource:
    adapter: SourceAdapter
    document: SourceDocument


class Resolver:
    def __init__(
        self,
        router: AdapterRouter,
        *,
        doi_resolver: DoiRedirectResolver | None = None,
    ) -> None:
        self.router = router
        self.doi_resolver = doi_resolver or DoiRedirectResolver()
        self._locks_guard = threading.Lock()
        self._adapter_locks: dict[str, threading.Lock] = {}

    @classmethod
    def empty(cls) -> Resolver:
        return cls(AdapterRouter())

    def _landing_url(self, value: str) -> str:
        candidate = value.strip()
        parsed = urlsplit(candidate)
        if parsed.scheme in {"http", "https"} and parsed.hostname:
            if parsed.hostname.casefold().rstrip(".") in _DOI_HOSTS:
                return canonical_landing_url(
                    self.doi_resolver.resolve(parsed.path.lstrip("/"))
                )
            return canonical_landing_url(candidate)
        normalized = normalize_doi(candidate)
        if normalized and _DOI.fullmatch(normalized):
            return canonical_landing_url(self.doi_resolver.resolve(normalized))
        raise AmbiguousInput(
            "title-only input requires canonical discovery before fetch; provide a DOI or official URL"
        )

    def _adapter_for(self, landing_url: str) -> SourceAdapter:
        adapter = self.router.adapter_for(landing_url)
        if adapter is None:
            hostname = (urlsplit(landing_url).hostname or "unknown host").casefold()
            raise UnsupportedPublisher(hostname)
        return adapter

    def resolve(self, value: str) -> ResolvedSource:
        landing_url = self._landing_url(value)
        adapter = self._adapter_for(landing_url)
        return ResolvedSource(adapter=adapter, document=adapter.resolve(landing_url))

    def acquire(self, value: str) -> AcquiredPair:
        resolved = self.resolve(value)
        return resolved.adapter.acquire(resolved.document)

    def acquire_exclusive(self, value: str) -> tuple[ResolvedSource, AcquiredPair]:
        """Resolve and acquire while no other thread uses the same adapter.

        Parallel batches give each publisher host its own worker, but a DOI can resolve to a
        host other than the one its record names; the lock keeps per-adapter state (such as
        the one IEEE browser) used by one paper at a time.
        """
        landing_url = self._landing_url(value)
        adapter = self._adapter_for(landing_url)
        with self._locks_guard:
            lock = self._adapter_locks.setdefault(adapter.name, threading.Lock())
        with lock:
            document = adapter.resolve(landing_url)
            return ResolvedSource(adapter=adapter, document=document), adapter.acquire(document)
