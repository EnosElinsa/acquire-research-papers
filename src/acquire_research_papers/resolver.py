from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote, urljoin, urlsplit

import httpx

from acquire_research_papers.acquisition.base import AcquiredPair, SourceAdapter, SourceDocument
from acquire_research_papers.acquisition.router import AdapterRouter
from acquire_research_papers.models import normalize_doi


class AmbiguousInput(ValueError):
    """An input cannot be mapped to exactly one supported official record."""


_DOI = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)


class DoiRedirectResolver:
    def __init__(self, endpoint: str = "https://doi.org/", timeout: float = 20.0) -> None:
        self.endpoint = endpoint.rstrip("/") + "/"
        self.timeout = timeout

    def resolve(self, doi: str) -> str:
        normalized = normalize_doi(doi)
        if not normalized or not _DOI.fullmatch(normalized):
            raise AmbiguousInput("input is not a valid DOI")
        url = urljoin(self.endpoint, quote(normalized, safe="/"))
        with httpx.Client(follow_redirects=False, timeout=self.timeout) as client:
            response = client.get(url, headers={"Accept": "text/html"})
        if response.status_code not in {301, 302, 303, 307, 308}:
            raise AmbiguousInput(f"DOI resolver returned HTTP {response.status_code}")
        location = response.headers.get("Location")
        target = urljoin(str(response.url), location or "")
        parsed = urlsplit(target)
        if not location or parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise AmbiguousInput("DOI resolver returned an unsafe redirect")
        return target


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

    @classmethod
    def empty(cls) -> Resolver:
        return cls(AdapterRouter())

    def _landing_url(self, value: str) -> str:
        candidate = value.strip()
        parsed = urlsplit(candidate)
        if parsed.scheme in {"http", "https"} and parsed.hostname:
            if parsed.hostname.casefold() in {"doi.org", "dx.doi.org"}:
                return self.doi_resolver.resolve(parsed.path.lstrip("/"))
            return candidate
        normalized = normalize_doi(candidate)
        if normalized and _DOI.fullmatch(normalized):
            return self.doi_resolver.resolve(normalized)
        raise AmbiguousInput(
            "title-only input requires canonical discovery before fetch; provide a DOI or official URL"
        )

    def resolve(self, value: str) -> ResolvedSource:
        landing_url = self._landing_url(value)
        adapter = self.router.adapter_for(landing_url)
        if adapter is None:
            raise AmbiguousInput("URL does not match a supported official publisher adapter")
        return ResolvedSource(adapter=adapter, document=adapter.resolve(landing_url))

    def acquire(self, value: str) -> AcquiredPair:
        resolved = self.resolve(value)
        return resolved.adapter.acquire(resolved.document)
