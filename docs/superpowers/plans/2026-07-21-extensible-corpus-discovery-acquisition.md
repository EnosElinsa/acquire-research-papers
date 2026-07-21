# Extensible Corpus Discovery and Acquisition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split corpus discovery from acquisition behind a frozen selection manifest, add a generic discovery-provider extension point, enforce declared corpus constraints, and deliver automatic or manual publisher pairs through one verified acquisition path.

**Architecture:** `CorpusDiscoveryWorkflow` converts a validated `CorpusSpec` into provider requests, merges field-level evidence, screens and plans the corpus, and atomically writes a hashed selection snapshot. `CorpusAcquisitionWorkflow` verifies that snapshot, routes only selected papers through existing publisher adapters, writes separate delivery/manual/retry states, and uses a safe metadata-driven layout. ACL and IJCAI are initial `DiscoveryProvider` implementations; no venue logic enters the coordinator or workflow.

**Tech Stack:** Python 3.11+, dataclasses and protocols, Beautiful Soup, httpx through `SafeHttpClient`, JSON Schema, PyYAML, pytest/pytest-httpserver, PowerShell and Node regression suites, Ruff, Git.

---

## File map

- Create `src/acquire_research_papers/discovery/contracts.py`: candidate, request, provider capability, batch, and diagnostic contracts.
- Create `src/acquire_research_papers/discovery/providers.py`: API-client wrapper and provider protocol helpers.
- Create `src/acquire_research_papers/discovery/coordinator.py`: capability slicing, provider isolation, identity merging, and diagnostics.
- Create `src/acquire_research_papers/discovery/official/acl.py`: ACL Anthology event-index discovery.
- Create `src/acquire_research_papers/discovery/official/ijcai.py`: IJCAI index/detail discovery.
- Create `src/acquire_research_papers/discovery/official/__init__.py`: official provider exports.
- Create `src/acquire_research_papers/selection.py`: safe numbered layouts and immutable selection snapshot I/O.
- Create `src/acquire_research_papers/acquisition/corpus.py`: selected-list acquisition, state ledger, and queues.
- Modify `src/acquire_research_papers/discovery/corpus.py`: re-export compatibility types, screening, constraint planning, and discovery-only workflow.
- Modify `src/acquire_research_papers/discovery/{crossref,openalex,semantic_scholar}.py`: import shared contracts and expose provider-safe query methods.
- Modify `src/acquire_research_papers/delivery.py`: allow verified delivery into reserved relative paths.
- Modify `src/acquire_research_papers/cli.py`: wire provider registry, separate workflows, explicit corpus acquisition, and selection-based manual import.
- Modify `src/acquire_research_papers/specs.py` and `schemas/corpus-spec.schema.json`: validate venue display metadata, quotas, and safe numbered templates.
- Modify `SKILL.md`, `README.md`, and `references/corpus-mode.md`: document the two explicit phases.
- Create `tests/unit/test_discovery_contracts.py`, `tests/unit/test_discovery_coordinator.py`, `tests/unit/test_selection.py`, `tests/unit/test_acl_discovery.py`, and `tests/unit/test_ijcai_discovery.py`.
- Replace the combined expectations in `tests/integration/test_corpus_cli.py` and add `tests/integration/test_corpus_acquire_cli.py` and `tests/integration/test_selected_manual_fetch_cli.py`.
- Add minimal official HTML under `tests/fixtures/discovery/acl/` and `tests/fixtures/discovery/ijcai/`.

### Task 1: Add typed discovery contracts and schema metadata

**Files:**
- Create: `src/acquire_research_papers/discovery/contracts.py`
- Modify: `src/acquire_research_papers/discovery/corpus.py:18-53`
- Modify: `src/acquire_research_papers/discovery/crossref.py:8`
- Modify: `src/acquire_research_papers/discovery/openalex.py:6`
- Modify: `src/acquire_research_papers/discovery/semantic_scholar.py:6`
- Modify: `schemas/corpus-spec.schema.json:20-64`
- Modify: `src/acquire_research_papers/specs.py:40-64`
- Test: `tests/unit/test_discovery_contracts.py`
- Test: `tests/unit/test_specs.py`

- [ ] **Step 1: Write failing request and schema tests**

```python
# tests/unit/test_discovery_contracts.py
from acquire_research_papers.discovery.contracts import DiscoveryRequest


def test_discovery_request_preserves_generic_venue_scope() -> None:
    request = DiscoveryRequest.from_spec(
        {
            "name": "generic corpus",
            "target": {"minimum": 1, "preferred": 2, "maximum": 3},
            "scope": {
                "venues": [{
                    "name": "Invented Proceedings",
                    "aliases": ["IP"],
                    "kind": "conference",
                    "short_name": "IP",
                    "publisher": "Invented Society",
                }],
                "years": {"include": [2026], "priority": [2026]},
                "publication_types": {"include": ["full"]},
                "topics": {"include": ["evolution"], "synonyms": ["genetic"]},
            },
        }
    )
    assert request.venues[0].all_names == ("Invented Proceedings", "IP")
    assert request.venues[0].short_name == "IP"
    assert request.venues[0].publisher == "Invented Society"
    assert request.queries == ("evolution", "genetic")
    assert request.maximum == 3
```

Append to `tests/unit/test_specs.py`:

```python
def test_corpus_spec_accepts_generic_layout_metadata(tmp_path: Path) -> None:
    path = tmp_path / "layout.yaml"
    path.write_text(
        "mode: corpus\nname: layout\ntarget:\n  minimum: 1\n  maximum: 2\n"
        "scope:\n  venues:\n    - name: Invented Proceedings\n"
        "      short_name: IP\n      publisher: Invented Society\n",
        encoding="utf-8",
    )
    spec = load_corpus_spec(path)
    assert spec["scope"]["venues"][0]["short_name"] == "IP"
```

- [ ] **Step 2: Run the focused tests and verify red**

Run: `uv run pytest tests/unit/test_discovery_contracts.py tests/unit/test_specs.py -q`

Expected: collection fails because `discovery.contracts` does not exist, or schema validation rejects `short_name`.

- [ ] **Step 3: Add the shared contracts and schema fields**

Create `discovery/contracts.py` with these public shapes and the existing candidate fields:

```python
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
    ) -> "DiscoveryRequest":
        return replace(
            self,
            venues=venues,
            years=years,
            year_priority=tuple(year for year in self.year_priority if year in years),
        )

    @classmethod
    def from_spec(cls, spec: dict[str, Any]) -> "DiscoveryRequest":
        scope = spec.get("scope", {})
        target = spec["target"]
        years = scope.get("years", {})
        types = scope.get("publication_types", {})
        topics = scope.get("topics", {})
        venues = tuple(
            VenueScope(
                name=str(item["name"]),
                aliases=tuple(item.get("aliases", ())),
                kind=str(item.get("kind", "")),
                issn=tuple(item.get("issn", ())),
                isbn=tuple(item.get("isbn", ())),
                short_name=str(item.get("short_name", "")),
                publisher=str(item.get("publisher", "")),
            )
            for item in scope.get("venues", ())
        )
        return cls(
            name=str(spec["name"]),
            venues=venues,
            years=tuple(years.get("include", ())),
            year_priority=tuple(years.get("priority", ())),
            included_types=tuple(types.get("include", ())),
            excluded_types=tuple(types.get("exclude", ())),
            include_topics=tuple(topics.get("include", ())),
            synonyms=tuple(topics.get("synonyms", ())),
            exclude_topics=tuple(topics.get("exclude", ())),
            minimum=int(target["minimum"]),
            preferred=int(target["preferred"]),
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
        return bool(requested & {value.casefold() for value in self.venue_aliases})

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
class DiscoveryBatch:
    candidates: tuple[CandidateMetadata, ...] = ()
    diagnostics: tuple[DiscoveryDiagnostic, ...] = ()
    covered_slices: tuple[str, ...] = ()


class DiscoveryProvider(Protocol):
    def capabilities(self) -> DiscoveryCapabilities: ...
    def discover(self, request: DiscoveryRequest) -> DiscoveryBatch: ...
```

Move `CandidateMetadata` and `CandidatePage` imports to this module, then re-export them from `discovery/corpus.py` so existing imports remain valid. Add optional `short_name` and `publisher` strings to each venue schema record.

- [ ] **Step 4: Add semantic validation for contradictory quotas**

In `load_corpus_spec`, reject each group where `maximum < minimum`, and reject a numbered profile without `{number}` and `{ext}`:

```python
for index, group in enumerate(spec["quotas"].get("groups", [])):
    maximum = group.get("maximum")
    if maximum is not None and maximum < group["minimum"]:
        raise SpecValidationError(
            f"quotas.groups.{index}.maximum: must be greater than or equal to minimum"
        )
delivery = spec["delivery"]
template = str(delivery.get("naming_template", ""))
if delivery.get("profile") == "numbered" and not {"{number}", "{ext}"}.issubset(template):
    raise SpecValidationError(
        "delivery.naming_template: numbered profile requires {number} and {ext}"
    )
```

- [ ] **Step 5: Run focused tests and the existing discovery-client tests**

Run: `uv run pytest tests/unit/test_discovery_contracts.py tests/unit/test_specs.py tests/unit/test_discovery_clients.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit the contracts**

```powershell
git add schemas/corpus-spec.schema.json src/acquire_research_papers/specs.py src/acquire_research_papers/discovery/contracts.py src/acquire_research_papers/discovery/corpus.py src/acquire_research_papers/discovery/crossref.py src/acquire_research_papers/discovery/openalex.py src/acquire_research_papers/discovery/semantic_scholar.py tests/unit/test_discovery_contracts.py tests/unit/test_specs.py
git commit -m "feat: add corpus discovery contracts"
```

### Task 2: Add the provider wrapper and generic coordinator

**Files:**
- Create: `src/acquire_research_papers/discovery/providers.py`
- Create: `src/acquire_research_papers/discovery/coordinator.py`
- Modify: `src/acquire_research_papers/discovery/__init__.py`
- Test: `tests/unit/test_discovery_coordinator.py`

- [ ] **Step 1: Write failing provider-isolation and DOI-merge tests**

```python
from acquire_research_papers.discovery.contracts import (
    CandidateMetadata, DiscoveryBatch, DiscoveryCapabilities, DiscoveryDiagnostic, DiscoveryRequest,
)
from acquire_research_papers.discovery.coordinator import DiscoveryCoordinator


class FakeProvider:
    def __init__(self, provider_id: str, batch: DiscoveryBatch) -> None:
        self.provider_id = provider_id
        self.batch = batch

    def capabilities(self) -> DiscoveryCapabilities:
        return DiscoveryCapabilities(self.provider_id, "official_index")

    def discover(self, request: DiscoveryRequest) -> DiscoveryBatch:
        return self.batch


def test_coordinator_merges_official_abstract_into_api_identity() -> None:
    api = CandidateMetadata(
        "api", "Same Paper", 2026, "Venue", 0.8, True, ("title",),
        doi="10.1000/same", provenance={"source": "crossref"},
    )
    official = CandidateMetadata(
        "official", "Same Paper", 2026, "Venue", 0.9, True,
        ("title", "abstract"), doi="10.1000/same", abstract="Official abstract",
        official_url="https://venue.example/paper", provenance={"source": "official"},
    )
    coordinator = DiscoveryCoordinator([
        FakeProvider("api", DiscoveryBatch((api,))),
        FakeProvider("official", DiscoveryBatch((official,))),
    ])
    batch = coordinator.discover(DiscoveryRequest.from_spec({
        "name": "x", "target": {"minimum": 1, "preferred": 1, "maximum": 2}
    }))
    assert len(batch.candidates) == 1
    assert batch.candidates[0].abstract == "Official abstract"
    assert set(batch.candidates[0].evidence_fields) == {"title", "abstract"}


def test_coordinator_records_one_provider_failure_and_continues() -> None:
    class BrokenProvider(FakeProvider):
        def discover(self, request: DiscoveryRequest) -> DiscoveryBatch:
            raise RuntimeError("page body with secret must not be copied")

    good = CandidateMetadata("good", "Good", 2026, "Venue", 0.9, True, ("title",))
    batch = DiscoveryCoordinator([
        BrokenProvider("broken", DiscoveryBatch()),
        FakeProvider("good", DiscoveryBatch((good,))),
    ]).discover(DiscoveryRequest.from_spec({
        "name": "x", "target": {"minimum": 1, "preferred": 1, "maximum": 2}
    }))
    assert [item.key for item in batch.candidates] == ["good"]
    assert batch.diagnostics[0].provider_id == "broken"
    assert batch.diagnostics[0].message == "provider failed during discovery"
```

- [ ] **Step 2: Run the coordinator tests and verify red**

Run: `uv run pytest tests/unit/test_discovery_coordinator.py -q`

Expected: collection fails because `DiscoveryCoordinator` is not defined.

- [ ] **Step 3: Implement query wrappers and isolated coordination**

Create `providers.py`:

```python
from dataclasses import dataclass
from typing import Callable, Iterable

from .contracts import (
    CandidateMetadata, DiscoveryBatch, DiscoveryCapabilities, DiscoveryRequest,
)


@dataclass(frozen=True)
class QueryApiProvider:
    provider_id: str
    searcher: Callable[[str, int], Iterable[CandidateMetadata]]
    configured: bool = True

    def capabilities(self) -> DiscoveryCapabilities:
        return DiscoveryCapabilities(
            provider_id=self.provider_id,
            source_class="metadata_api",
            requires_credentials=not self.configured,
        )

    def discover(self, request: DiscoveryRequest) -> DiscoveryBatch:
        if not self.configured:
            return DiscoveryBatch()
        found: list[CandidateMetadata] = []
        for query in request.queries:
            found.extend(self.searcher(query, request.maximum))
        return DiscoveryBatch(candidates=tuple(found), covered_slices=(self.provider_id,))
```

Create `coordinator.py` with normalized identity and merge helpers. Exception messages written to diagnostics must be fixed public messages; exception text stays out of files:

```python
def candidate_identity(candidate: CandidateMetadata) -> str:
    if candidate.doi:
        return f"doi:{normalize_doi(candidate.doi)}"
    if candidate.official_url:
        return f"url:{candidate.official_url.rstrip('/').casefold()}"
    return "meta:" + "|".join((
        _normalized(candidate.title), str(candidate.year), _normalized(candidate.venue)
    ))


class DiscoveryCoordinator:
    def __init__(self, providers: Iterable[DiscoveryProvider]) -> None:
        self.providers = tuple(providers)

    def discover(self, request: DiscoveryRequest) -> DiscoveryBatch:
        merged: dict[str, CandidateMetadata] = {}
        diagnostics: list[DiscoveryDiagnostic] = []
        covered: list[str] = []
        for provider in self.providers:
            capability = provider.capabilities()
            supported = tuple(
                venue for venue in request.venues if capability.supports(venue)
            )
            if request.venues and not supported:
                continue
            supported_years = tuple(
                year for year in request.years if capability.supports_year(year)
            )
            if request.years and not supported_years:
                continue
            provider_request = request.with_scope(
                supported or request.venues,
                supported_years or request.years,
            )
            try:
                batch = provider.discover(provider_request)
            except (RateLimited, NetworkTransient):
                diagnostics.append(DiscoveryDiagnostic(
                    capability.provider_id, "discover", "network_transient",
                    "provider temporarily unavailable", retryable=True,
                ))
                continue
            except (HttpStatusError, RuntimeError, ValueError):
                diagnostics.append(DiscoveryDiagnostic(
                    capability.provider_id, "discover", "provider_error",
                    "provider failed during discovery",
                ))
                continue
            diagnostics.extend(batch.diagnostics)
            covered.extend(batch.covered_slices)
            for candidate in batch.candidates:
                identity = candidate_identity(candidate)
                try:
                    merged[identity] = merge_candidates(merged.get(identity), candidate)
                except CandidateConflict:
                    diagnostics.append(DiscoveryDiagnostic(
                        capability.provider_id, "merge", "identity_conflict",
                        "candidate identity fields conflict",
                    ))
        return DiscoveryBatch(tuple(merged.values()), tuple(diagnostics), tuple(covered))
```

Define the merge operation explicitly:

```python
class CandidateConflict(ValueError):
    pass


_METADATA_SOURCES = {"crossref", "openalex", "semantic-scholar"}


def _is_official(candidate: CandidateMetadata) -> bool:
    return str(candidate.provenance.get("source", "")) not in _METADATA_SOURCES


def _pick(previous: CandidateMetadata, current: CandidateMetadata, field: str):
    old = getattr(previous, field)
    new = getattr(current, field)
    if new and (not old or (_is_official(current) and not _is_official(previous))):
        return new
    return old


def merge_candidates(
    previous: CandidateMetadata | None,
    current: CandidateMetadata,
) -> CandidateMetadata:
    if previous is None:
        return current
    if previous.doi and current.doi and normalize_doi(previous.doi) != normalize_doi(current.doi):
        raise CandidateConflict("conflicting DOI")
    if previous.year and current.year and previous.year != current.year:
        raise CandidateConflict("conflicting year")
    if previous.venue and current.venue and _normalized(previous.venue) != _normalized(current.venue):
        raise CandidateConflict("conflicting venue")
    field_provenance = {
        key: tuple(dict.fromkeys((*previous.field_provenance.get(key, ()), *values)))
        for key, values in current.field_provenance.items()
    }
    for key, values in previous.field_provenance.items():
        field_provenance.setdefault(key, values)
    return replace(
        previous,
        key=_pick(previous, current, "key"),
        title=_pick(previous, current, "title"),
        venue=_pick(previous, current, "venue"),
        doi=_pick(previous, current, "doi"),
        official_url=_pick(previous, current, "official_url"),
        authors=_pick(previous, current, "authors"),
        abstract=_pick(previous, current, "abstract"),
        publication_type=_pick(previous, current, "publication_type"),
        track=_pick(previous, current, "track"),
        publication_date=_pick(previous, current, "publication_date"),
        relevance_score=max(previous.relevance_score, current.relevance_score),
        hard_gates_passed=previous.hard_gates_passed and current.hard_gates_passed,
        evidence_fields=tuple(dict.fromkeys((*previous.evidence_fields, *current.evidence_fields))),
        keywords=tuple(dict.fromkeys((*previous.keywords, *current.keywords))),
        related_ids=tuple(dict.fromkeys((*previous.related_ids, *current.related_ids))),
        citation_count=max(previous.citation_count, current.citation_count),
        field_provenance=field_provenance,
        source_records=(*previous.source_records, *current.source_records),
    )
```

Add a test with the same official URL but different years and assert one `identity_conflict` diagnostic is written instead of merging the records.

- [ ] **Step 4: Run coordinator and client regressions**

Run: `uv run pytest tests/unit/test_discovery_coordinator.py tests/unit/test_discovery_clients.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit the coordinator**

```powershell
git add src/acquire_research_papers/discovery/providers.py src/acquire_research_papers/discovery/coordinator.py src/acquire_research_papers/discovery/__init__.py tests/unit/test_discovery_coordinator.py
git commit -m "feat: coordinate corpus discovery providers"
```

### Task 3: Enforce group and recent-window constraints

**Files:**
- Modify: `src/acquire_research_papers/discovery/corpus.py:89-173`
- Modify: `tests/unit/test_corpus.py`

- [ ] **Step 1: Add failing maximum and recent-ratio tests**

```python
def test_group_maximum_is_never_exceeded() -> None:
    spec = {
        "target": {"minimum": 2, "preferred": 3, "maximum": 3},
        "quotas": {"groups": [
            {"name": "conference", "minimum": 1, "maximum": 1, "venues": ["Conf"]}
        ]},
    }
    plan = CorpusPlanner(spec).select([
        candidate("c1", 2026, 0.99, venue="Conf"),
        candidate("c2", 2026, 0.98, venue="Conf"),
        candidate("j1", 2026, 0.90, venue="Journal"),
    ])
    assert [item.key for item in plan.auto_accepted] == ["c1", "j1"]
    assert plan.quota_shortfalls == ()


def test_recent_window_ratio_uses_publication_date() -> None:
    spec = {
        "target": {"minimum": 2, "preferred": 2, "maximum": 3},
        "quotas": {"recent_window": {"from": "2025-07-18", "minimum_ratio": 0.5}},
    }
    old = replace(candidate("old", 2026, 0.99), publication_date="2025-01-01")
    recent = replace(candidate("recent", 2025, 0.86), publication_date="2025-08-01")
    plan = CorpusPlanner(spec).select([old, recent])
    assert {item.key for item in plan.auto_accepted} == {"old", "recent"}
    assert plan.quota_shortfalls == ()


def test_named_quota_shortfall_does_not_lower_screening_threshold() -> None:
    spec = {
        "target": {"minimum": 2, "preferred": 2, "maximum": 2},
        "quotas": {"groups": [
            {"name": "journals", "minimum": 2, "venues": ["Journal"]}
        ]},
    }
    plan = CorpusPlanner(spec).select([
        candidate("journal", 2026, 0.90, venue="Journal"),
        candidate("border", 2026, 0.70, venue="Journal"),
    ])
    assert plan.quota_shortfalls == ("group:journals:1", "global:1")
```

- [ ] **Step 2: Run the planner tests and verify red**

Run: `uv run pytest tests/unit/test_corpus.py -q`

Expected: failures show group maximum and `quota_shortfalls` are not implemented.

- [ ] **Step 3: Implement deterministic constraint additions**

Extend `CorpusPlan` with `quota_shortfalls: tuple[str, ...]`. Add these helpers to `CorpusPlanner`:

```python
def _group_count(self, selected: list[CandidateMetadata], group: dict[str, Any]) -> int:
    return sum(self._matches_group(item, group) for item in selected)

def _can_add(self, selected: list[CandidateMetadata], candidate: CandidateMetadata) -> bool:
    for group in self.spec.get("quotas", {}).get("groups", []):
        maximum = group.get("maximum")
        if maximum is None or not self._matches_group(candidate, group):
            continue
        if self._group_count(selected, group) >= int(maximum):
            return False
    return True

@staticmethod
def _is_recent(candidate: CandidateMetadata, start: date) -> bool:
    if not candidate.publication_date:
        return False
    try:
        return date.fromisoformat(candidate.publication_date) >= start
    except ValueError:
        return False
```

Selection order must be: group minimums in spec order, recent-window minimum for the planned total, then ranked fill. Every addition calls `_can_add`. After selection, compute shortfalls as `group:<name>:<missing>`, `recent:<missing>`, and `global:<missing>` in that order. Pending candidates never fill a quota.

- [ ] **Step 4: Run all corpus planner tests**

Run: `uv run pytest tests/unit/test_corpus.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit the constraint fix**

```powershell
git add src/acquire_research_papers/discovery/corpus.py tests/unit/test_corpus.py
git commit -m "fix: enforce corpus quota constraints"
```

### Task 4: Build safe layouts and frozen selection snapshots

**Files:**
- Create: `src/acquire_research_papers/selection.py`
- Modify: `src/acquire_research_papers/artifacts.py`
- Test: `tests/unit/test_selection.py`

- [ ] **Step 1: Write failing layout, traversal, and hash tests**

```python
import json
from pathlib import Path

import pytest

from acquire_research_papers.discovery.contracts import CandidateMetadata, VenueScope
from acquire_research_papers.selection import SelectionStore, build_selection_records


def _candidate() -> CandidateMetadata:
    return CandidateMetadata(
        "paper", "Paper", 2026, "Invented Proceedings", 0.95, True,
        ("title", "abstract"), doi="10.1000/paper",
        official_url="https://publisher.example/paper", abstract="Relevant abstract",
    )


def test_numbered_layout_is_metadata_driven_and_contiguous(tmp_path: Path) -> None:
    venue = VenueScope(
        "Invented Proceedings", short_name="IP", publisher="Invented Society"
    )
    records = build_selection_records(
        [_candidate(), _candidate().__class__(**{**_candidate().to_dict(), "key": "paper-2", "doi": "10.1000/paper-2"})],
        venues=(venue,),
        delivery={
            "profile": "numbered",
            "naming_template": "2026.7.18 {publisher} {venue_short}/{number}.{ext}",
        },
    )
    assert records[0].relative_pdf == "2026.7.18 Invented Society IP/1.pdf"
    assert records[1].relative_bibtex == "2026.7.18 Invented Society IP/2.bib"


def test_numbered_layout_rejects_parent_traversal() -> None:
    with pytest.raises(ValueError, match="unsafe relative delivery path"):
        build_selection_records(
            [_candidate()], venues=(VenueScope("Invented Proceedings", short_name="IP"),),
            delivery={"profile": "numbered", "naming_template": "../{number}.{ext}"},
        )


def test_selection_store_rejects_modified_jsonl(tmp_path: Path) -> None:
    store = SelectionStore.write(tmp_path, {"name": "test"}, ())
    store.selected_path.write_text('{"selection_id":"changed"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="selection SHA-256 mismatch"):
        SelectionStore.load(store.manifest_path)
```

- [ ] **Step 2: Run selection tests and verify red**

Run: `uv run pytest tests/unit/test_selection.py -q`

Expected: collection fails because `selection.py` does not exist.

- [ ] **Step 3: Implement selection records, safe rendering, and hashing**

Create `selection.py` with frozen `SelectionRecord` and `SelectionStore` dataclasses. Use canonical UTF-8 JSON lines and `sha256_bytes`:

```python
@dataclass(frozen=True)
class SelectionRecord:
    selection_id: str
    ordinal: int
    key: str
    title: str
    authors: tuple[str, ...]
    doi: str | None
    official_url: str | None
    venue: str
    venue_short: str
    publisher: str
    year: int
    publication_date: str | None
    publication_type: str | None
    track: str | None
    abstract: str
    keywords: tuple[str, ...]
    evidence_fields: tuple[str, ...]
    relative_pdf: str
    relative_bibtex: str
    relative_provenance: str


def _safe_relative(value: str) -> str:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.name:
        raise ValueError("unsafe relative delivery path")
    for part in path.parts:
        if re.search(r'[<>:"|?*]', part) or part.rstrip(" .").casefold() in _WINDOWS_RESERVED:
            raise ValueError("unsafe relative delivery path")
    return path.as_posix()


def _jsonl(records: tuple[SelectionRecord, ...]) -> bytes:
    return "".join(
        json.dumps(asdict(record), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for record in records
    ).encode("utf-8")
```

Define the Windows reserved-name set used above before `_safe_relative`:

```python
_WINDOWS_RESERVED = frozenset(
    {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
     *(f"lpt{i}" for i in range(1, 10))}
)
```

For numbered layouts, match the candidate venue against `VenueScope.all_names`, copy `short_name` and `publisher` into the record, render PDF and BibTeX with identical metadata and different `ext`, number independently inside each rendered parent folder, and set provenance to `<parent>/<number>.provenance.json`. Derive `selection_id` as the first 24 hexadecimal characters of SHA-256 over `doi:<normalized-doi>`, otherwise `url:<canonical-url>`, otherwise `meta:<normalized-title>|<year>|<normalized-venue>`. Reject missing template metadata and path collisions before writing. Generic layout retains the current title/key bundle pattern.

`SelectionStore.write(root, spec, records, *, discovery_summary=None)` atomically writes `selected-papers.jsonl` and `selection-manifest.json`; the manifest contains `schema_version: 1`, canonical spec, `spec_sha256`, `selected_sha256`, record count, provider coverage, discovery diagnostic count, quota counts/shortfalls, and the selected file's relative name. `SelectionStore.load` resolves the selected file inside the manifest directory, rejects traversal, verifies the hash, and parses only known fields.

- [ ] **Step 4: Run selection and atomic-write tests**

Run: `uv run pytest tests/unit/test_selection.py tests/unit/test_artifacts.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit selection snapshots**

```powershell
git add src/acquire_research_papers/selection.py src/acquire_research_papers/artifacts.py tests/unit/test_selection.py
git commit -m "feat: freeze corpus selection snapshots"
```

### Task 5: Make corpus discovery planning-only

**Files:**
- Modify: `src/acquire_research_papers/discovery/corpus.py:248-455`
- Modify: `src/acquire_research_papers/cli.py:109-210,411-455,530-551`
- Replace: `tests/integration/test_corpus_cli.py`

- [ ] **Step 1: Replace the combined CLI test with a discovery-only test**

```python
def test_discover_corpus_writes_frozen_list_without_acquiring(tmp_path, capsys) -> None:
    spec = tmp_path / "job.yaml"
    spec.write_text(
        "mode: corpus\nname: split\ntarget:\n  minimum: 1\n  preferred: 1\n  maximum: 2\n",
        encoding="utf-8",
    )
    candidate = CandidateMetadata(
        "high", "High", 2026, "Test", 0.91, True, ("title", "abstract"),
        doi="10.1000/high", abstract="Relevant abstract",
    )
    acquired: list[str] = []
    workflow = CorpusDiscoveryWorkflow(
        discoverer=lambda request: DiscoveryBatch((candidate,)),
    )
    app = Application.for_test(
        app_root=tmp_path / "app", repository_root=tmp_path / "repository",
        corpus_discovery=workflow,
    )
    output = tmp_path / "output"
    assert run_cli([
        "discover", "corpus", "--spec", str(spec), "--output", str(output)
    ], application=app) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "planned"
    assert Path(payload["selected"]).is_file()
    assert not (output / "acquisition-manifest.jsonl").exists()
    assert not list(output.rglob("*.pdf"))
    assert acquired == []
```

- [ ] **Step 2: Run the integration test and verify red**

Run: `uv run pytest tests/integration/test_corpus_cli.py -q`

Expected: import or assertion failures show the combined `CorpusWorkflow` still performs acquisition.

- [ ] **Step 3: Replace the combined workflow with `CorpusDiscoveryWorkflow`**

The workflow constructor accepts `Callable[[DiscoveryRequest], DiscoveryBatch]`. Its `run(spec, output)` sequence is fixed:

```python
request = DiscoveryRequest.from_spec(spec)
batch = self.discoverer(request)
candidates = [CorpusDiscoverer._screen(item, spec) for item in batch.candidates]
plan = CorpusPlanner(spec).select(candidates)
records = candidate_ledger(candidates, plan)
write_candidates(destination / "candidates.jsonl", records)
write_pending(destination / "pending-review.csv", plan)
write_diagnostics(destination / "discovery-errors.jsonl", batch.diagnostics)
selected = build_selection_records(
    plan.auto_accepted, venues=request.venues, delivery=spec["delivery"]
)
selection = SelectionStore.write(
    destination,
    spec,
    selected,
    discovery_summary={
        "provider_coverage": list(batch.covered_slices),
        "discovery_errors": len(batch.diagnostics),
        "quota_shortfalls": list(plan.quota_shortfalls),
    },
)
write_corpus_manifest(destination, plan, batch, selection)
```

Remove `acquirer`, `acquisition_path`, `manual_download_path`, `delivered`, and `deferred` from the discovery result. `shortfall` is selection shortfall. Diagnostic records use `asdict` and atomic JSONL output.

Change `Application` fields to `corpus_discovery` and `corpus_acquisition`; `for_test` accepts both independently. `discover corpus` emits `candidates`, `selected`, `pending_review`, `discovery_errors`, `selection_manifest`, counts, quota shortfalls, and no acquisition fields.

The command never writes PDF or BibTeX files; a regression test scans the discovery output tree for both extensions.

- [ ] **Step 4: Run discovery CLI, planner, and spec tests**

Run: `uv run pytest tests/integration/test_corpus_cli.py tests/unit/test_corpus.py tests/unit/test_specs.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit the phase split**

```powershell
git add src/acquire_research_papers/discovery/corpus.py src/acquire_research_papers/cli.py tests/integration/test_corpus_cli.py
git commit -m "refactor: separate corpus discovery phase"
```

### Task 6: Add frozen-list corpus acquisition and queues

**Files:**
- Create: `src/acquire_research_papers/acquisition/corpus.py`
- Modify: `src/acquire_research_papers/delivery.py:23-113`
- Modify: `src/acquire_research_papers/cli.py:212-408,411-620`
- Create: `tests/integration/test_corpus_acquire_cli.py`
- Modify: `tests/unit/test_delivery.py`

- [ ] **Step 1: Write failing target-path and acquisition-state tests**

Append to `tests/unit/test_delivery.py`:

```python
def test_delivery_uses_reserved_verified_paths(tmp_path: Path, verified_pair) -> None:
    result = GenericDelivery(tmp_path / "out").deliver(
        pair=verified_pair,
        paper_id="paper-1",
        relative_paths=(Path("Venue/1.pdf"), Path("Venue/1.bib"), Path("Venue/1.provenance.json")),
    )
    assert result.pdf == (tmp_path / "out" / "Venue" / "1.pdf").resolve()
    assert result.bibtex.name == "1.bib"
```

Create `tests/integration/test_corpus_acquire_cli.py` with a valid `SelectionStore`, two records, and this outcome stub:

```python
def acquirer(record, output):
    if record.key == "blocked":
        return {"status": "manual_required", "error_code": "access_required", "message": "login"}
    return {
        "status": "delivered",
        "pdf": str(output / record.relative_pdf),
        "bibtex": str(output / record.relative_bibtex),
        "provenance": str(output / record.relative_provenance),
    }
```

Assert `arp acquire corpus --selection ... --output ...` calls both records, writes one `delivered` and one `manual_required`, puts only the blocked record in `manual-download.csv`, writes an empty `retryable-downloads.csv`, and does not change `selected-papers.jsonl` bytes.

Run the same workflow a second time with a call-counting acquirer. Include `pdf_sha256`, `bibtex_sha256`, and `provenance_sha256` in the delivered stub outcome, create matching target files, and assert the previously delivered record is not passed to the acquirer while the manual-required record is passed again.

- [ ] **Step 2: Run focused tests and verify red**

Run: `uv run pytest tests/unit/test_delivery.py tests/integration/test_corpus_acquire_cli.py -q`

Expected: `GenericDelivery.deliver` rejects `relative_paths`, and the `acquire corpus` parser is missing.

- [ ] **Step 3: Allow safe reserved paths in delivery**

Add an optional tuple to `GenericDelivery.deliver` and resolve each member underneath the delivery root:

```python
def _reserved_paths(self, values: tuple[Path, Path, Path]) -> DeliveryResult:
    resolved = tuple((self.root / value).resolve() for value in values)
    if any(path == self.root or self.root not in path.parents for path in resolved):
        raise ValueError("reserved delivery path escapes the delivery root")
    return DeliveryResult(pdf=resolved[0], bibtex=resolved[1], provenance=resolved[2])
```

Keep the existing slug paths when `relative_paths` is absent. All existing PDF, BibTeX, provenance, hash, and identity validation remains unchanged.

- [ ] **Step 4: Implement `CorpusAcquisitionWorkflow`**

Create `acquisition/corpus.py` with `AcquisitionRunResult` and a workflow that loads `SelectionStore`, snapshots the selected bytes, invokes an injected acquirer for every record, normalizes states, and atomically writes all ledgers. State mapping is exact:

```python
_MANUAL_CODES = {"access_required", "manual_publisher_download", "unsupported_adapter"}
_RETRYABLE_CODES = {"network_transient", "rate_limited"}


def normalized_state(outcome: dict[str, Any]) -> str:
    if outcome.get("status") == "delivered":
        return "delivered"
    code = str(outcome.get("error_code", "contract_error"))
    if code in _MANUAL_CODES:
        return "manual_required"
    if code in _RETRYABLE_CODES:
        return "retryable"
    return "contract_error"
```

Before invoking the acquirer, load the last `acquisition-manifest.jsonl`. Reuse a prior `delivered` row only when its three paths equal the selection's reserved paths, all three files exist under the delivery root, and their current SHA-256 values equal `pdf_sha256`, `bibtex_sha256`, and `provenance_sha256` in that row. Every other prior state is attempted again. `Application.acquire_selected` includes those three hashes in a delivered outcome.

`manual-download.csv` fields are `selection_id,ordinal,title,doi,official_url,publisher,reason,message,target_pdf,target_bibtex`. `retryable-downloads.csv` uses the same identity fields plus `reason,message`. The delivery manifest records total, delivered, manual_required, retryable, contract_error, complete, and the selection SHA-256. Before returning, assert the selected bytes still equal the verified snapshot.

- [ ] **Step 5: Add the CLI command and application method**

Add:

```python
acquire = subparsers.add_parser("acquire", help="acquire a frozen corpus selection")
acquire_modes = acquire.add_subparsers(dest="acquire_mode", required=True)
acquire_corpus = acquire_modes.add_parser("corpus")
acquire_corpus.add_argument("--selection", type=Path, required=True)
acquire_corpus.add_argument("--output", type=Path, required=True)
```

`Application.acquire_selected(record, output)` uses `record.doi or record.official_url`, resolves/acquires through the existing router, and calls `_deliver_pair` with the three reserved relative paths. Map `AccessRequired` to `manual_required`, `RateLimited`/`NetworkTransient` to `retryable`, and identity/page errors to `contract_error`. The CLI calls only `app.corpus_acquisition.run` and emits the delivery-manifest and queue paths.

- [ ] **Step 6: Run acquisition and existing fetch tests**

Run: `uv run pytest tests/integration/test_corpus_acquire_cli.py tests/integration/test_fetch_cli.py tests/unit/test_delivery.py -q`

Expected: all tests pass.

- [ ] **Step 7: Commit acquisition**

```powershell
git add src/acquire_research_papers/acquisition/corpus.py src/acquire_research_papers/delivery.py src/acquire_research_papers/cli.py tests/integration/test_corpus_acquire_cli.py tests/unit/test_delivery.py
git commit -m "feat: acquire frozen corpus selections"
```

### Task 7: Add selection-based manual verification

**Files:**
- Modify: `src/acquire_research_papers/acquisition/manual_handoff.py`
- Modify: `src/acquire_research_papers/cli.py:304-363,420-430,485-515`
- Create: `tests/integration/test_selected_manual_fetch_cli.py`

- [ ] **Step 1: Write a failing selected-manual-import test**

```python
from pypdf import PdfWriter


def make_selection(root: Path):
    candidate = CandidateMetadata(
        "manual", "Manual Paper", 2026, "Manual Journal", 0.95, True,
        ("title", "abstract"), authors=("Ada Lovelace",),
        official_url="https://publisher.example/manual", abstract="Relevant abstract",
    )
    records = build_selection_records(
        [candidate],
        venues=(VenueScope(
            "Manual Journal", short_name="MJ", publisher="Manual Publisher"
        ),),
        delivery={
            "profile": "numbered",
            "naming_template": "Manual Publisher MJ/{number}.{ext}",
        },
    )
    store = SelectionStore.write(root, {"name": "manual"}, records)
    return store, records[0]


def write_matching_pair(root: Path, record: SelectionRecord) -> tuple[Path, Path]:
    root.mkdir(parents=True)
    pdf = root / "manual.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.add_metadata({"/Title": record.title})
    with pdf.open("wb") as handle:
        writer.write(handle)
    bib = root / "manual.bib"
    bib.write_text(
        "@article{manual,title={Manual Paper},author={Lovelace, Ada},"
        "year={2026},journal={Manual Journal}}",
        encoding="utf-8",
    )
    return pdf, bib


def configured_application(tmp_path: Path) -> Application:
    return Application.for_test(
        app_root=tmp_path / "app",
        repository_root=tmp_path / "repository",
        manual_selection=ManualSelectionWorkflow(opener=lambda _: True),
    )


def test_manual_fetch_selection_imports_to_reserved_paths(tmp_path, capsys) -> None:
    store, record = make_selection(tmp_path / "selection")
    pdf, bib = write_matching_pair(tmp_path / "downloads", record)
    app = configured_application(tmp_path)
    code = run_cli([
        "manual-fetch", "--selection", str(store.manifest_path),
        "--key", record.selection_id, "--output", str(tmp_path / "delivery"),
        "--pdf", str(pdf), "--bibtex", str(bib), "--no-open",
    ], application=app)
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert Path(payload["pdf"]) == (tmp_path / "delivery" / record.relative_pdf).resolve()
    assert pdf.is_file() and bib.is_file()
```

Add a second test that changes one byte in `selected-papers.jsonl` and expects exit code 64 with `selection SHA-256 mismatch` before either local source file is read.

- [ ] **Step 2: Run the selected manual tests and verify red**

Run: `uv run pytest tests/integration/test_selected_manual_fetch_cli.py -q`

Expected: parser rejects `--selection` and `--key`.

- [ ] **Step 3: Reuse the generic watcher with selected metadata**

Add `document_from_selection(record)` to `manual_handoff.py`:

```python
def document_from_selection(record: SelectionRecord) -> SourceDocument:
    if not record.official_url:
        raise ValueError("selected paper has no official URL for manual handoff")
    host = urlsplit(record.official_url).hostname
    if not host:
        raise ValueError("selected paper official URL is invalid")
    metadata = PaperMetadata(
        title=record.title,
        authors=record.authors,
        year=record.year,
        venue=record.venue,
        doi=record.doi,
        publisher=record.publisher or host,
        landing_url=record.official_url,
        publication_type=record.publication_type,
    )
    return SourceDocument(metadata, record.official_url, record.official_url, frozenset({host}))
```

Add `ManualSelectionWorkflow.acquire(record, ...)` that snapshots `ManualDownloadWatcher`, optionally opens only `record.official_url`, then calls `validate_manual_pair` for explicit paths or `wait_for_pair` for watched files. It returns the existing `ManualHandoffSelection`; source files remain untouched.

Add `manual_selection: ManualSelectionWorkflow | None` to `Application` and `Application.for_test`; production construction uses `ManualSelectionWorkflow(opener=webbrowser.open)` without attaching to or inspecting the browser.

- [ ] **Step 4: Add mutually exclusive manual CLI inputs**

Make `--input` optional and add `--selection` plus `--key`. Validate exactly one mode:

```python
single_mode = bool(args.input)
selection_mode = bool(args.selection and args.key)
if single_mode == selection_mode:
    raise AmbiguousInput(
        "manual-fetch requires either --input or both --selection and --key"
    )
```

In selection mode, load and verify the store, find exactly one selection ID, run `ManualSelectionWorkflow`, then call `_deliver_pair` with reserved paths and `acquisition_method=manual_publisher_download`. Do not use the Elsevier API resolver in this mode.

- [ ] **Step 5: Run all manual-fetch tests**

Run: `uv run pytest tests/integration/test_selected_manual_fetch_cli.py tests/integration/test_manual_fetch_cli.py -q`

Expected: all tests pass, including the existing ScienceDirect-only mode.

- [ ] **Step 6: Commit selected manual handoff**

```powershell
git add src/acquire_research_papers/acquisition/manual_handoff.py src/acquire_research_papers/cli.py tests/integration/test_selected_manual_fetch_cli.py
git commit -m "feat: verify manual corpus selections"
```

### Task 8: Add ACL Anthology official-index discovery

**Files:**
- Create: `src/acquire_research_papers/discovery/official/__init__.py`
- Create: `src/acquire_research_papers/discovery/official/acl.py`
- Create: `tests/fixtures/discovery/acl/event.html`
- Create: `tests/unit/test_acl_discovery.py`

- [ ] **Step 1: Add a minimal event fixture and failing parser test**

The fixture contains one `2025.acl-long.1` article with title, abstract, authors, DOI/PDF/Bib links; one `2025.acl-short.2`; and one volume front matter entry.

```html
<main>
  <article data-anthology-id="2025.acl-long.1">
    <h5><a href="/2025.acl-long.1/">Evolutionary Multi-Agent Language Models</a></h5>
    <span class="authors">Ada Lovelace; Alan Turing</span>
    <div class="abstract">Multi-agent evolutionary collaboration.</div>
    <a href="/2025.acl-long.1.pdf">pdf</a>
    <a href="/2025.acl-long.1.bib">bib</a>
  </article>
  <article data-anthology-id="2025.acl-short.2">
    <h5><a href="/2025.acl-short.2/">Short Multi-Agent Note</a></h5>
    <div class="abstract">Short paper abstract.</div>
  </article>
  <article data-anthology-id="2025.acl-long.0">
    <h5><a href="/2025.acl-long.0/">Proceedings of ACL 2025</a></h5>
    <span class="type">front matter</span>
  </article>
</main>
```

```python
def test_acl_provider_emits_only_requested_long_papers(fixture_server) -> None:
    fixture_server.serve_text(
        "/events/acl-2025/", (FIXTURES / "event.html").read_text(encoding="utf-8")
    )
    provider = AclAnthologyDiscoveryProvider(
        client=fixture_server.client,
        event_template=fixture_server.url("/events/acl-{year}/"),
        production_hosts={fixture_server.host},
    )
    request = DiscoveryRequest.from_spec({
        "name": "acl", "target": {"minimum": 1, "preferred": 1, "maximum": 10},
        "scope": {
            "venues": [{"name": "Annual Meeting of the Association for Computational Linguistics", "aliases": ["ACL"]}],
            "years": {"include": [2025]},
            "publication_types": {"include": ["full"]},
            "topics": {"include": ["multi-agent"]},
        },
    })
    batch = provider.discover(request)
    assert [item.key for item in batch.candidates] == ["2025.acl-long.1"]
    assert batch.candidates[0].abstract == "Multi-agent evolutionary collaboration."
    assert batch.candidates[0].doi == "10.18653/v1/2025.acl-long.1"
```

- [ ] **Step 2: Run the ACL test and verify red**

Run: `uv run pytest tests/unit/test_acl_discovery.py -q`

Expected: import fails because the provider does not exist.

- [ ] **Step 3: Implement the ACL provider contract**

`capabilities()` advertises official-index source class, title/abstract/authors/venue/type/DOI fields, and ACL venue aliases. `discover()` returns an empty successful batch for requests without a matching venue, fetches one event page per requested year, and parses only IDs matching `^\d{4}\.acl-long\.\d+$` when full/long/regular types are requested.

Each candidate uses:

```python
CandidateMetadata(
    key=anthology_id,
    title=title,
    year=year,
    venue=official_venue,
    relevance_score=0.0,
    hard_gates_passed=True,
    evidence_fields=("title", "abstract", "authors", "venue", "publication_type"),
    doi=f"10.18653/v1/{anthology_id}",
    official_url=urljoin(origin, f"/{anthology_id}/"),
    authors=authors,
    abstract=abstract,
    keywords=keywords,
    publication_type="full",
    track="long",
    provenance={"source": "acl-anthology", "event_url": event_url},
    field_provenance={field: ("acl-anthology",) for field in evidence_fields},
)
```

Missing event structure produces one sanitized `page_contract_changed` diagnostic for that year, never a silent successful empty page.

- [ ] **Step 4: Test track exclusion and page drift**

Add assertions that short/front-matter entries never appear and an event page without article records returns one diagnostic with no page body in the message.

Run: `uv run pytest tests/unit/test_acl_discovery.py tests/unit/test_acl_adapter.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit ACL discovery**

```powershell
git add src/acquire_research_papers/discovery/official/__init__.py src/acquire_research_papers/discovery/official/acl.py tests/fixtures/discovery/acl/event.html tests/unit/test_acl_discovery.py
git commit -m "feat: discover ACL papers from official index"
```

### Task 9: Add IJCAI official-index discovery

**Files:**
- Create: `src/acquire_research_papers/discovery/official/ijcai.py`
- Create: `tests/fixtures/discovery/ijcai/index.html`
- Create: `tests/fixtures/discovery/ijcai/paper.html`
- Create: `tests/unit/test_ijcai_discovery.py`

- [ ] **Step 1: Add index/detail fixtures and a failing main-track test**

The index fixture contains a Main Track section with one relevant and one irrelevant title, plus a Demo Track entry. The paper fixture contains exact citation metadata, abstract, keywords, track text, visible PDF, and visible BibTeX links.

```html
<!-- tests/fixtures/discovery/ijcai/index.html -->
<h2>Main Track</h2>
<div class="paper_wrapper"><a href="/proceedings/2025/12">Evolutionary Optimization for Large Language Models</a></div>
<div class="paper_wrapper"><a href="/proceedings/2025/13">Classical Theorem Proving</a></div>
<h2>Demo Track</h2>
<div class="paper_wrapper"><a href="/proceedings/2025/99">Evolutionary Demo System</a></div>
```

```html
<!-- tests/fixtures/discovery/ijcai/paper.html -->
<meta name="citation_title" content="Evolutionary Optimization for Large Language Models">
<meta name="citation_author" content="Ada Lovelace">
<meta name="citation_publication_date" content="2025/08/01">
<meta name="citation_conference_title" content="Proceedings of IJCAI 2025">
<meta name="citation_doi" content="10.24963/ijcai.2025/12">
<meta name="citation_pdf_url" content="https://www.ijcai.org/proceedings/2025/0012.pdf">
<p>Main Track. Pages 100-108</p>
<section id="abstract">We optimize a large language model with evolutionary search.</section>
<meta name="keywords" content="large language model; evolutionary optimization">
<a href="/proceedings/2025/0012.pdf">PDF</a>
<a href="/proceedings/2025/bibtex/12">BibTeX</a>
```

```python
def test_ijcai_provider_prefilters_and_emits_main_track_detail(fixture_server) -> None:
    fixture_server.serve_text("/proceedings/2025/", INDEX.read_text(encoding="utf-8"))
    fixture_server.serve_text("/proceedings/2025/12", PAPER.read_text(encoding="utf-8"))
    provider = IjcaiDiscoveryProvider(
        client=fixture_server.client,
        index_template=fixture_server.url("/proceedings/{year}/"),
        production_hosts={fixture_server.host},
    )
    request = DiscoveryRequest.from_spec({
        "name": "ijcai", "target": {"minimum": 1, "preferred": 1, "maximum": 10},
        "scope": {
            "venues": [{"name": "International Joint Conference on Artificial Intelligence", "aliases": ["IJCAI"]}],
            "years": {"include": [2025]},
            "publication_types": {"include": ["main"]},
            "topics": {"include": ["evolutionary optimization"]},
        },
    })
    batch = provider.discover(request)
    assert [item.key for item in batch.candidates] == ["10.24963/ijcai.2025/12"]
    assert batch.candidates[0].track == "Main Track"
    assert "large language model" in batch.candidates[0].abstract.casefold()
```

- [ ] **Step 2: Run the IJCAI test and verify red**

Run: `uv run pytest tests/unit/test_ijcai_discovery.py -q`

Expected: import fails because `IjcaiDiscoveryProvider` does not exist.

- [ ] **Step 3: Implement index enumeration and verified detail parsing**

`capabilities()` advertises IJCAI aliases and official evidence. The index parser walks headings and paper links while retaining the current track. It fetches detail pages only when the normalized title or subsection contains a positive query term. The detail parser reuses the acquisition adapter's landing-path, DOI, track, visible-link, and metadata invariants rather than weakening them.

Emit candidates with official detail URL, normalized DOI, title, authors, abstract, keywords, `publication_type="main"`, `track="Main Track"`, and field provenance. Reject demo/special tracks before candidate emission. A malformed detail page produces one paper-level diagnostic and allows later papers to continue.

- [ ] **Step 4: Add page-drift and wrong-track assertions**

Assert that the demo detail URL is never requested, an irrelevant Main Track title is not requested, and one malformed relevant detail page yields a diagnostic while another valid detail remains in the batch.

Run: `uv run pytest tests/unit/test_ijcai_discovery.py tests/unit/test_ijcai_adapter.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit IJCAI discovery**

```powershell
git add src/acquire_research_papers/discovery/official/ijcai.py tests/fixtures/discovery/ijcai/index.html tests/fixtures/discovery/ijcai/paper.html tests/unit/test_ijcai_discovery.py
git commit -m "feat: discover IJCAI papers from official index"
```

### Task 10: Register providers without venue branches in the core

**Files:**
- Modify: `src/acquire_research_papers/cli.py:152-210`
- Modify: `src/acquire_research_papers/discovery/coordinator.py`
- Modify: `tests/integration/test_corpus_cli.py`
- Modify: `tests/unit/test_discovery_coordinator.py`

- [ ] **Step 1: Add a fake-venue end-to-end extension test**

```python
def test_fake_provider_extends_corpus_without_core_venue_changes(tmp_path, capsys) -> None:
    provider = FakeProviderForVenue("Invented Proceedings")
    app = Application.for_test(
        app_root=tmp_path / "app",
        repository_root=tmp_path / "repo",
        corpus_discovery=CorpusDiscoveryWorkflow(
            discoverer=DiscoveryCoordinator([provider]).discover
        ),
    )
    spec = write_invented_venue_spec(tmp_path)
    assert run_cli([
        "discover", "corpus", "--spec", str(spec), "--output", str(tmp_path / "run")
    ], application=app) == 0
    selected = (tmp_path / "run" / "selected-papers.jsonl").read_text(encoding="utf-8")
    assert "Invented Proceedings" in selected
```

The fake provider lives only in the test and is passed through the registry; no production file names the invented venue.

- [ ] **Step 2: Run the extension test and verify red if wiring still assumes query searchers**

Run: `uv run pytest tests/integration/test_corpus_cli.py::test_fake_provider_extends_corpus_without_core_venue_changes -q`

Expected: failure shows production/test application wiring still expects the old `CorpusDiscoverer([searcher])` shape.

- [ ] **Step 3: Wire production providers through one registry list**

In `Application.default`, construct:

```python
providers: list[DiscoveryProvider] = [
    QueryApiProvider("crossref", crossref.corpus_searcher),
    AclAnthologyDiscoveryProvider(
        client=SafeHttpClient(allowed_hosts={"aclanthology.org"})
    ),
    IjcaiDiscoveryProvider(
        client=SafeHttpClient(allowed_hosts={"www.ijcai.org"})
    ),
]
openalex_key = os.environ.get("OPENALEX_API_KEY", "").strip()
if openalex_key:
    openalex = OpenAlexClient(
        client=SafeHttpClient(allowed_hosts={"api.openalex.org"}), api_key=openalex_key
    )
    providers.append(QueryApiProvider("openalex", openalex.corpus_searcher))
semantic_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "").strip()
if semantic_key:
    semantic = SemanticScholarClient(
        client=SafeHttpClient(allowed_hosts={"api.semanticscholar.org"}),
        api_key=semantic_key,
    )
    providers.append(QueryApiProvider("semantic-scholar", semantic.corpus_searcher))
coordinator = DiscoveryCoordinator(providers)
```

Add a separate `search_endpoint` constructor value defaulting to `https://api.semanticscholar.org/graph/v1/paper/search` and implement search without changing the recommendation method:

```python
def corpus_searcher(self, query: str, rows: int) -> tuple[CandidateMetadata, ...]:
    fields = (
        "paperId,title,abstract,venue,year,publicationDate,publicationTypes,"
        "authors,externalIds,url,citationCount"
    )
    parameters = {
        "query": query,
        "limit": max(1, min(rows, 100)),
        "fields": fields,
    }
    url = f"{self.search_endpoint}?{urlencode(parameters)}"
    headers = {"x-api-key": self.api_key} if self.api_key else None
    payload = self.client.get(url, headers=headers).json()
    return tuple(self._candidate(item) for item in payload.get("data") or ())
```

The query URL stored in provenance must exclude the API key because the key is sent only in the header. Application wiring names providers, not venue activation rules. Instantiate `CorpusDiscoveryWorkflow(coordinator.discover)` and `CorpusAcquisitionWorkflow(application.acquire_selected)` independently.

- [ ] **Step 4: Verify optional providers fail closed without keys**

Add tests with both environment variables absent and assert production construction registers Crossref plus official providers without trying OpenAlex or Semantic Scholar. Add a coordinator test proving an optional provider error writes a diagnostic and does not abort official providers.

Run: `uv run pytest tests/unit/test_discovery_coordinator.py tests/unit/test_discovery_clients.py tests/integration/test_corpus_cli.py tests/integration/test_corpus_acquire_cli.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit provider wiring**

```powershell
git add src/acquire_research_papers/cli.py src/acquire_research_papers/discovery/coordinator.py src/acquire_research_papers/discovery/semantic_scholar.py tests/unit/test_discovery_coordinator.py tests/unit/test_discovery_clients.py tests/integration/test_corpus_cli.py
git commit -m "feat: register extensible corpus providers"
```

### Task 11: Update the skill contract and run full verification

**Files:**
- Modify: `SKILL.md`
- Modify: `README.md`
- Modify: `references/corpus-mode.md`
- Modify: `scripts/validate_skill.py` only if it validates the old combined output names
- Test: `tests/unit/test_no_sensitive_artifacts.py`
- Test: `tests/unit/test_skill_layout.py`

- [ ] **Step 1: Write the documentation contract test first**

Append to `tests/unit/test_no_sensitive_artifacts.py`:

```python
def test_skill_documents_two_stage_corpus_contract() -> None:
    root = Path(__file__).resolve().parents[2]
    text = (root / "SKILL.md").read_text(encoding="utf-8")
    assert "arp discover corpus" in text
    assert "arp acquire corpus" in text
    assert "selected-papers.jsonl" in text
    assert "manual-download.csv" in text
    assert "automatically acquires selected" not in text
```

- [ ] **Step 2: Run the documentation test and verify red**

Run: `uv run pytest tests/unit/test_no_sensitive_artifacts.py::test_skill_documents_two_stage_corpus_contract -q`

Expected: failure because `SKILL.md` still describes automatic acquisition inside discovery.

- [ ] **Step 3: Update all user-facing commands and invariants**

Document exactly:

```powershell
uv run --project $skill arp discover corpus --spec <job.yaml> --output <discovery-run>
uv run --project $skill arp acquire corpus `
  --selection <discovery-run\selection-manifest.json> --output <delivery-root>
```

State that discovery produces `candidates.jsonl`, `selected-papers.jsonl`, `pending-review.csv`, `discovery-errors.jsonl`, and `selection-manifest.json` without publisher artifacts. State that acquisition never changes selection; it produces verified pairs, `manual-download.csv`, `retryable-downloads.csv`, and `delivery-manifest.json`. Preserve every IEEE, ScienceDirect, credential, BibTeX, MinerU, and Markdown hard stop verbatim. In particular, IEEE credential release remains exact-host-only and stops on CAPTCHA, OTP, or incomplete login; ScienceDirect remains manual-only and no browser session, cookies, or organization login are automated.

- [ ] **Step 4: Run focused Python tests**

Run: `uv run pytest tests/unit/test_no_sensitive_artifacts.py tests/unit/test_skill_layout.py tests/unit/test_specs.py tests/unit/test_corpus.py tests/unit/test_selection.py -q`

Expected: all tests pass.

- [ ] **Step 5: Run the complete deterministic verification matrix**

Run each command separately:

```powershell
uv run pytest -q
node --test tests/node/test-ieee-playwright.mjs
powershell -NoProfile -ExecutionPolicy Bypass -File tests/powershell/test-secret-store.ps1
uv run ruff check .
uv run python scripts/validate_skill.py
```

Expected:

- pytest reports all tests passed;
- Node reports zero failed tests;
- PowerShell reports all credential groups passed;
- Ruff reports `All checks passed!`;
- skill validation reports the skill is valid.

- [ ] **Step 6: Run live smoke checks within existing access boundaries**

Use a one-paper ACL or IJCAI spec to run discovery and then acquisition into a temporary directory outside the repository. Confirm discovery writes no PDF/BibTeX and acquisition verifies one official pair. Retry one IEEE DOI only once; if institutional login remains incomplete, assert the selection stays present and the acquisition writes `manual_required`. Do not automate ScienceDirect; confirm a ScienceDirect selection enters the manual queue.

- [ ] **Step 7: Commit documentation and final validation changes**

```powershell
git add SKILL.md README.md references/corpus-mode.md scripts/validate_skill.py tests/unit/test_no_sensitive_artifacts.py tests/unit/test_skill_layout.py
git commit -m "docs: document two-stage corpus workflow"
```

- [ ] **Step 8: Verify final repository state**

Run:

```powershell
git status --short
git log --oneline -12
```

Expected: working tree is clean and the task commits appear in dependency order.

## Post-implementation corpus execution

After every implementation task and validation gate passes, run the already-normalized student 2 `CorpusSpec` through the two commands. Inspect the frozen selection counts, venue groups, recent-window ratio, and pending-review list before acquisition. Then run acquisition over the entire frozen list, allow all automatic adapters to finish, and give the user one consolidated `manual-download.csv` for remaining official PDF/BibTeX pairs. Re-run corpus acquisition after manual imports and verify final folder numbering, hashes, manifest counts, and absence of gaps before reporting completion.
