from __future__ import annotations

import re
from urllib.parse import urlsplit

from acquire_research_papers.acquisition.base import (
    AccessRequired,
    AcquiredPair,
    NotOfficial,
    PageContractChanged,
    SourceDocument,
)
from acquire_research_papers.http import SafeHttpClient


SCIENCEDIRECT_HOST = "www.sciencedirect.com"
_PII_PATH = re.compile(r"^/science/article/(?:abs/)?pii/([A-Z0-9]+)/?$")


class ScienceDirectAdapter:
    """Route ScienceDirect references to the explicit manual handoff."""

    name = "sciencedirect"

    def __init__(
        self,
        *,
        client: SafeHttpClient | None = None,
        production_hosts: set[str] | frozenset[str] = frozenset({SCIENCEDIRECT_HOST}),
    ) -> None:
        # Kept as a constructor argument for adapter compatibility; it is never used.
        self.client = client
        self.production_hosts = frozenset(host.casefold() for host in production_hosts)

    @classmethod
    def for_production(cls) -> ScienceDirectAdapter:
        return cls()

    def supports(self, landing_url: str) -> bool:
        parsed = urlsplit(landing_url)
        return bool(parsed.hostname and parsed.hostname.casefold() in self.production_hosts)

    def resolve(self, landing_url: str) -> SourceDocument:
        parsed = urlsplit(landing_url)
        if not self.supports(landing_url):
            raise NotOfficial("ScienceDirect landing URL is outside the official host")
        if not _PII_PATH.fullmatch(parsed.path):
            raise PageContractChanged("ScienceDirect landing path has no canonical PII")
        raise AccessRequired(
            "ScienceDirect downloads are manual-only; run arp manual-fetch for this article"
        )

    def acquire(self, document: SourceDocument) -> AcquiredPair:
        raise AccessRequired(
            "ScienceDirect downloads are manual-only; run arp manual-fetch for this article"
        )
