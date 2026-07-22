from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any, Protocol


@dataclass(frozen=True)
class VenueScope:
    name: str
    aliases: tuple[str, ...] = ()
    kind: str = ""
    issn: tuple[str, ...] = ()
    isbn: tuple[str, ...] = ()
    short_name: str = ""
    publisher: str = ""

    @property
    def all_names(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)


@dataclass(frozen=True)
class DiscoveryRequest:
    name: str
    venues: tuple[VenueScope, ...]
    years: tuple[int, ...]
    year_priority: tuple[int, ...]
    included_types: tuple[str, ...]
    excluded_types: tuple[str, ...]
    include_topics: tuple[str, ...]
    synonyms: tuple[str, ...]
    exclude_topics: tuple[str, ...]
    minimum: int
    preferred: int
    maximum: int

    @property
    def queries(self) -> tuple[str, ...]:
        return self.include_topics + self.synonyms or (self.name,)

    def with_scope(
        self,
        venues: tuple[VenueScope, ...],
        years: tuple[int, ...],
    ) -> DiscoveryRequest:
        return replace(
            self,
            venues=venues,
            years=years,
            year_priority=tuple(year for year in self.year_priority if year in years),
        )

    @classmethod
    def from_spec(cls, spec: dict[str, Any]) -> DiscoveryRequest:
        scope = spec.get("scope", {})
        target = spec["target"]
        years = scope.get("years", {})
        publication_types = scope.get("publication_types", {})
        topics = scope.get("topics", {})
        venues = tuple(
            VenueScope(
                name=str(item["name"]),
                aliases=tuple(str(value) for value in item.get("aliases", ())),
                kind=str(item.get("kind", "")),
                issn=tuple(str(value) for value in item.get("issn", ())),
                isbn=tuple(str(value) for value in item.get("isbn", ())),
                short_name=str(item.get("short_name", "")),
                publisher=str(item.get("publisher", "")),
            )
            for item in scope.get("venues", ())
        )
        preferred = int(target.get("preferred", target["maximum"]))
        return cls(
            name=str(spec["name"]),
            venues=venues,
            years=tuple(int(year) for year in years.get("include", ())),
            year_priority=tuple(int(year) for year in years.get("priority", ())),
            included_types=tuple(str(value) for value in publication_types.get("include", ())),
            excluded_types=tuple(str(value) for value in publication_types.get("exclude", ())),
            include_topics=tuple(str(value) for value in topics.get("include", ())),
            synonyms=tuple(str(value) for value in topics.get("synonyms", ())),
            exclude_topics=tuple(str(value) for value in topics.get("exclude", ())),
            minimum=int(target["minimum"]),
            preferred=preferred,
            maximum=int(target["maximum"]),
        )


@dataclass(frozen=True)
class CandidateMetadata:
    key: str
    title: str
    year: int
    venue: str
    relevance_score: float
    hard_gates_passed: bool
    evidence_fields: tuple[str, ...]
    doi: str | None = None
    official_url: str | None = None
    authors: tuple[str, ...] = ()
    abstract: str = ""
    keywords: tuple[str, ...] = ()
    publication_type: str | None = None
    track: str | None = None
    publication_date: str | None = None
    citation_count: int = 0
    related_ids: tuple[str, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)
    field_provenance: dict[str, tuple[str, ...]] = field(default_factory=dict)
    source_records: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CandidatePage:
    candidates: tuple[CandidateMetadata, ...]
    next_cursor: str | None = None


@dataclass(frozen=True)
class DiscoveryCapabilities:
    provider_id: str
    source_class: str
    venue_aliases: frozenset[str] = frozenset()
    supported_years: frozenset[int] = frozenset()
    evidence_fields: frozenset[str] = frozenset()
    requires_credentials: bool = False

    def supports(self, venue: VenueScope) -> bool:
        if not self.venue_aliases:
            return True
        requested = {value.casefold() for value in venue.all_names}
        supported = {value.casefold() for value in self.venue_aliases}
        return bool(requested & supported)

    def supports_year(self, year: int) -> bool:
        return not self.supported_years or year in self.supported_years


@dataclass(frozen=True)
class DiscoveryDiagnostic:
    provider_id: str
    phase: str
    error_code: str
    message: str
    venue: str = ""
    year: int | None = None
    url: str = ""
    retryable: bool = False


@dataclass(frozen=True)
class CoverageSlice:
    provider_id: str
    venue: str
    year: int
    state: str
    pages_fetched: int = 0
    records_fetched: int = 0
    next_cursor: str | None = None
    diagnostic_code: str = ""

    def __post_init__(self) -> None:
        if self.state not in {"complete", "partial", "failed"}:
            raise ValueError("coverage state must be complete, partial, or failed")
        if self.pages_fetched < 0 or self.records_fetched < 0:
            raise ValueError("coverage counters must not be negative")

    @property
    def label(self) -> str:
        return f"{self.provider_id}:{self.venue}:{self.year}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DiscoveryBatch:
    candidates: tuple[CandidateMetadata, ...] = ()
    diagnostics: tuple[DiscoveryDiagnostic, ...] = ()
    covered_slices: tuple[str, ...] = ()
    coverage: tuple[CoverageSlice, ...] = ()

    @property
    def complete_slice_labels(self) -> tuple[str, ...]:
        labels = [*self.covered_slices]
        labels.extend(item.label for item in self.coverage if item.state == "complete")
        return tuple(dict.fromkeys(labels))


class DiscoveryProvider(Protocol):
    def capabilities(self) -> DiscoveryCapabilities: ...

    def discover(self, request: DiscoveryRequest) -> DiscoveryBatch: ...


class DiscoveryEnricher(Protocol):
    def capabilities(self) -> DiscoveryCapabilities: ...

    def enrich(
        self,
        candidates: tuple[CandidateMetadata, ...],
        request: DiscoveryRequest,
    ) -> DiscoveryBatch: ...
