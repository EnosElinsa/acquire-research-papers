from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlsplit


class PaperStatus(str, Enum):
    DISCOVERED = "discovered"
    AUTO_ACCEPTED = "auto_accepted"
    PENDING_REVIEW = "pending_review"
    REJECTED = "rejected"
    RESOLVING = "resolving"
    DOWNLOADED = "downloaded"
    PAIR_VERIFIED = "pair_verified"
    TEMPORARILY_PARSED = "temporarily_parsed"
    NUMBERED = "numbered"
    DELIVERED = "delivered"


class ErrorCode(str, Enum):
    NOT_FOUND = "not_found"
    NOT_OFFICIAL = "not_official"
    ACCESS_REQUIRED = "access_required"
    AUTH_INTERACTIVE = "auth_interactive"
    RATE_LIMITED = "rate_limited"
    PDF_INVALID = "pdf_invalid"
    BIB_MISSING = "bib_missing"
    METADATA_MISMATCH = "metadata_mismatch"
    DUPLICATE = "duplicate"
    SCREENING_AMBIGUOUS = "screening_ambiguous"
    PAGE_CONTRACT_CHANGED = "page_contract_changed"
    NETWORK_TRANSIENT = "network_transient"


_DOI_PREFIX = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE)


def normalize_doi(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = _DOI_PREFIX.sub("", value.strip()).strip().lower()
    return normalized or None


@dataclass(frozen=True)
class PaperMetadata:
    title: str
    authors: tuple[str, ...]
    year: int
    venue: str
    doi: str | None
    publisher: str
    landing_url: str
    publication_type: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("title", "publisher", "landing_url"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be empty")
        parsed = urlsplit(self.landing_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("landing_url must be an HTTP(S) URL")
        if not 1000 <= self.year <= 9999:
            raise ValueError("year must be a four-digit year")
        object.__setattr__(self, "title", self.title.strip())
        object.__setattr__(self, "authors", tuple(author.strip() for author in self.authors))
        object.__setattr__(self, "venue", self.venue.strip())
        object.__setattr__(self, "publisher", self.publisher.strip())
        object.__setattr__(self, "doi", normalize_doi(self.doi))
