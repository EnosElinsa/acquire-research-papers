from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from acquire_research_papers.models import PaperMetadata


class PageContractChanged(RuntimeError):
    """A publisher page no longer has one unambiguous official artifact contract."""


class AccessRequired(RuntimeError):
    """The official artifact exists but the current context lacks entitlement."""


class NotOfficial(RuntimeError):
    """A candidate artifact is not hosted or exported by the publisher."""


@dataclass(frozen=True)
class SourceDocument:
    metadata: PaperMetadata
    pdf_url: str
    bibtex_url: str
    allowed_hosts: frozenset[str]


@dataclass(frozen=True)
class AcquiredPair:
    document: SourceDocument
    pdf_bytes: bytes
    bibtex_text: str
    bibtex_bytes: bytes | None = None
    bibtex_source: str = "publisher_download"

    @property
    def citation_bytes(self) -> bytes:
        return self.bibtex_bytes if self.bibtex_bytes is not None else self.bibtex_text.encode("utf-8")


class SourceAdapter(Protocol):
    name: str

    def supports(self, landing_url: str) -> bool: ...

    def resolve(self, landing_url: str) -> SourceDocument: ...

    def acquire(self, document: SourceDocument) -> AcquiredPair: ...
