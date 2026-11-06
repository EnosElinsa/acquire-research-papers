from __future__ import annotations

import html
import re
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

from acquire_research_papers.discovery.contracts import DiscoveryRequest
from acquire_research_papers.discovery.corpus import CandidateMetadata
from acquire_research_papers.discovery.coordinator import candidate_identity, merge_candidates
from acquire_research_papers.discovery.providers import matches_query_filters, query_filters
from acquire_research_papers.discovery.venue_presets import find_preset
from acquire_research_papers.mineru import MineruCache, MineruResult
from acquire_research_papers.research.delivery import ResearchDelivery, ResearchDeliveryResult
from acquire_research_papers.research.evidence import EvidenceRecord
from acquire_research_papers.research.planner import ResearchPlan, ResearchPlanner
from acquire_research_papers.research.saturation import StepYield, assess


_ISSN = re.compile(r"\d{4}-\d{3}[\dXx]")


def _normalized(value: object) -> str:
    # Crossref writes some venue names with HTML entities ("Surveys &amp; Tutorials").
    return " ".join(re.findall(r"\w+", html.unescape(str(value)).casefold()))


@lru_cache(maxsize=64)
def _venue_scope(venues: tuple[str, ...]) -> tuple[frozenset[str], frozenset[str]]:
    """Normalized venue names and ISSNs a research scope accepts.

    Each scope entry is an ISSN, a venue name, or a built-in preset's ID, short name, name,
    or alias; a preset entry accepts all of the preset's names and ISSNs.
    """
    names: set[str] = set()
    issns: set[str] = set()
    for venue in venues:
        if _ISSN.fullmatch(venue.strip()):
            issns.add(venue.strip().upper())
            continue
        names.add(_normalized(venue))
        preset = find_preset(venue)
        if preset is not None:
            names.update(_normalized(value) for value in
                         (preset.name, preset.short_name, *preset.aliases))
            issns.update(value.upper() for value in preset.issn)
    return frozenset(names), frozenset(issns)


@dataclass(frozen=True)
class ScopedSearcher:
    """A keyword search that applies the research scope (years, filters) at its source.

    ``search(query, rows, request)`` receives the scope as a ``DiscoveryRequest``, so the
    source returns in-scope papers instead of the top results of all years. A source without
    an ISSN filter (``issn_filter=False``) searches by the journals' names when
    ``name_filter`` is set and every scope venue is a known journal, and otherwise without
    a journal restriction; the scope check then drops out-of-scope venues.
    """

    provider_id: str
    search: Callable[[str, int, DiscoveryRequest], Iterable[CandidateMetadata]]
    issn_filter: bool = True
    name_filter: bool = False

    def request_for(self, request: DiscoveryRequest) -> DiscoveryRequest:
        filters = request.query_filters
        if filters.issns and not self.issn_filter and not (
                self.name_filter and filters.venue_names):
            return replace(request, query_filters=replace(filters, issns=(), venue_names=()))
        return request


@lru_cache(maxsize=64)
def _filter_request(years: tuple[int, ...], publication_types: tuple[str, ...],
                    doi_prefixes: tuple[str, ...], issns: tuple[str, ...],
                    title_terms: tuple[str, ...], rows: int) -> DiscoveryRequest:
    request = DiscoveryRequest.from_spec({
        "name": "research scope", "target": {"minimum": 0, "maximum": max(1, rows)},
        "scope": {"years": {"include": list(years)}}})
    return replace(request, query_filters=query_filters(
        publication_types=publication_types, doi_prefixes=doi_prefixes, issns=issns,
        title_terms=title_terms))


def _strings(scope: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = scope.get(key)
    return tuple(str(item) for item in value) if isinstance(value, (list, tuple)) else ()


def scope_request(scope: Mapping[str, object], rows: int = 25) -> DiscoveryRequest:
    """The research scope as a search request: years, types, DOI prefixes, title terms, and
    the venues' ISSNs when every scope venue is an ISSN or a known journal."""
    years = scope.get("years")
    year_values = tuple(sorted({int(year) for year in years})) if isinstance(
        years, (list, tuple)) else ()
    venues = _strings(scope, "venues")
    per_venue = [_venue_scope((venue,))[1] for venue in venues]
    issns = tuple(sorted(set().union(*per_venue))) if per_venue and all(per_venue) else ()
    return _filter_request(year_values, _strings(scope, "publication_types"),
                           _strings(scope, "doi_prefixes"), issns,
                           _strings(scope, "title_terms"), rows)


@dataclass(frozen=True)
class ResearchWorkflowResult:
    status: str
    query_passes: int
    delivery: ResearchDeliveryResult
    saturation_signals: tuple[str, ...] = ()
    next_actions: tuple[dict[str, str], ...] = ()


@dataclass(frozen=True)
class CitationEdge:
    source_id: str
    target_id: str
    direction: str
    provider: str
    seed: str


@dataclass(frozen=True)
class GraphDiagnostic:
    seed: str
    direction: str
    provider: str
    error: str


@dataclass(frozen=True)
class GraphBounds:
    seed_limit: int
    neighbors_per_direction: int
    requested_seeds: tuple[str, ...] = ()
    expanded_seeds: tuple[str, ...] = ()
    skipped_seeds: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResearchDiscovery(Sequence[CandidateMetadata]):
    candidates: tuple[CandidateMetadata, ...]
    edges: tuple[CitationEdge, ...] = ()
    diagnostics: tuple[GraphDiagnostic, ...] = ()
    graph_bounds: GraphBounds = field(
        default_factory=lambda: GraphBounds(0, 0)
    )
    # Search saturation record (see research.saturation); empty for custom discoverers.
    saturation: dict[str, Any] = field(default_factory=dict)

    def __iter__(self) -> Iterator[CandidateMetadata]:
        return iter(self.candidates)

    def __len__(self) -> int:
        return len(self.candidates)

    def __getitem__(self, index):
        return self.candidates[index]


class ResearchDiscoverer:
    def __init__(
        self,
        searchers: Iterable[Callable[[str, int], Iterable[CandidateMetadata]] | ScopedSearcher],
        *,
        graph_expanders: Iterable[
            Callable[[str, str, int], Iterable[CandidateMetadata]]
        ] = (),
        rows_per_query: int = 25,
        maximum: int = 100,
        graph_limit: int = 25,
        graph_seed_limit: int = 3,
    ) -> None:
        self.searchers = tuple(searchers)
        self.graph_expanders = tuple(graph_expanders)
        self.rows_per_query = rows_per_query
        self.maximum = maximum
        self.graph_limit = graph_limit
        self.graph_seed_limit = graph_seed_limit

    @staticmethod
    def _paper_id(candidate: CandidateMetadata) -> str:
        return candidate.doi or candidate.key

    @staticmethod
    def _provider(expander, candidate: CandidateMetadata | None = None) -> str:
        if candidate is not None:
            source = str(candidate.provenance.get("source") or "")
            if source:
                return source
        if isinstance(expander, ScopedSearcher):
            return expander.provider_id
        owner = getattr(expander, "__self__", None)
        return str(getattr(owner, "graph_provider_id", "graph-provider"))

    @staticmethod
    def _in_scope(
        candidate: CandidateMetadata,
        scope: Mapping[str, object],
    ) -> bool:
        years = scope.get("years")
        if isinstance(years, (list, tuple)) and years and candidate.year not in {
            int(year) for year in years
        }:
            return False

        venues = scope.get("venues")
        if isinstance(venues, (list, tuple)) and venues:
            names, issns = _venue_scope(tuple(str(venue) for venue in venues))
            candidate_issns = {
                str(value).upper()
                for record in (candidate.provenance, *candidate.source_records)
                if isinstance(record, Mapping)
                for value in record.get("issn") or ()
            }
            if _normalized(candidate.venue) not in names and not (candidate_issns & issns):
                return False
        # Publication type, DOI prefix, and title terms, checked as discover candidates does.
        if not matches_query_filters(candidate, scope_request(scope)):
            return False
        haystack = _normalized(
            " ".join(
                (
                    candidate.title,
                    candidate.abstract,
                    candidate.venue,
                    *candidate.keywords,
                )
            )
        )
        include_terms = scope.get("include_terms")
        if isinstance(include_terms, (list, tuple)) and include_terms:
            if not any(_normalized(term) in haystack for term in include_terms):
                return False
        exclude_terms = scope.get("exclude_terms")
        if isinstance(exclude_terms, (list, tuple)) and any(
            _normalized(term) in haystack for term in exclude_terms
        ):
            return False
        return True

    def __call__(
        self,
        plan: ResearchPlan,
        *,
        analysis: Mapping[str, object] | None = None,
        scope: Mapping[str, object] | None = None,
    ) -> ResearchDiscovery:
        settings: Mapping[str, Any] = analysis or {}
        research_scope = scope or {}
        graph_limit = int(settings.get("graph_neighbors_per_direction", self.graph_limit))
        graph_seed_limit = int(settings.get("graph_seed_limit", self.graph_seed_limit))
        rows_per_query = int(settings.get("rows_per_query", self.rows_per_query))
        maximum = int(settings.get("max_candidates", self.maximum))
        discovered: dict[str, CandidateMetadata] = {}
        query_passes: dict[str, list[str]] = {}
        diagnostics: list[GraphDiagnostic] = []
        pass_yields: list[StepYield] = []
        search_scope = scope_request(research_scope, rows_per_query)

        def search(searcher, text: str) -> tuple[tuple[CandidateMetadata, ...], Exception | None]:
            try:
                if isinstance(searcher, ScopedSearcher):
                    return tuple(searcher.search(text, rows_per_query,
                                                 searcher.request_for(search_scope))), None
                return tuple(searcher(text, rows_per_query)), None
            except Exception as exc:  # recorded by class name only
                return (), exc

        for query in plan.queries:
            seen_before = set(discovered)
            returned: set[str] = set()
            failed = 0
            if len(self.searchers) > 1:
                # Each searcher is a different service: ask them at the same time and merge
                # the answers in searcher order, so the result does not depend on timing.
                with ThreadPoolExecutor(max_workers=len(self.searchers),
                                        thread_name_prefix="arp-research-search") as pool:
                    outcomes = list(pool.map(lambda item: search(item, query.query),
                                             self.searchers))
            else:
                outcomes = [search(searcher, query.query) for searcher in self.searchers]
            for searcher, (searched, error) in zip(self.searchers, outcomes, strict=True):
                if error is not None:
                    failed += 1
                    diagnostics.append(
                        GraphDiagnostic(
                            seed="",
                            direction=f"search:{query.kind}",
                            provider=self._provider(searcher),
                            error=type(error).__name__,
                        )
                    )
                    continue
                for candidate in searched:
                    if not self._in_scope(candidate, research_scope):
                        continue
                    key = candidate_identity(candidate)
                    returned.add(key)
                    discovered[key] = merge_candidates(discovered.get(key), candidate)
                    passes = query_passes.setdefault(key, [])
                    if query.kind not in passes:
                        passes.append(query.kind)
            pass_yields.append(StepYield(query.kind, len(returned), len(returned - seen_before),
                                         failed))
        initially_ranked = sorted(
            discovered.items(),
            key=lambda item: (
                -item[1].relevance_score,
                -item[1].citation_count,
                -item[1].year,
                item[0],
            ),
        )
        explicit_requests = tuple(plan.graph_requests)
        if explicit_requests:
            requested_seeds = tuple(request.seed for request in explicit_requests)
            graph_requests = tuple(
                (request.seed, request.directions)
                for request in explicit_requests[:graph_seed_limit]
            )
        else:
            inferred_requests = tuple(
                (self._paper_id(candidate), ("references", "citations", "related"))
                for _, candidate in initially_ranked
                if self._paper_id(candidate)
            )
            requested_seeds = tuple(seed for seed, _ in inferred_requests)
            graph_requests = inferred_requests[:graph_seed_limit]
        expanded_seeds = tuple(seed for seed, _ in graph_requests)
        graph_bounds = GraphBounds(
            seed_limit=graph_seed_limit,
            neighbors_per_direction=graph_limit,
            requested_seeds=requested_seeds,
            expanded_seeds=expanded_seeds,
            skipped_seeds=requested_seeds[len(expanded_seeds) :],
        )
        graph_paths: dict[str, list[dict[str, str]]] = {}
        edges: list[CitationEdge] = []
        frontier_yields: list[StepYield] = []
        for seed, directions in graph_requests:
            for direction in directions:
                seen_before = set(discovered)
                returned = set()
                failed = 0
                for expander in self.graph_expanders:
                    try:
                        expanded = tuple(expander(seed, direction, graph_limit))
                    except Exception as exc:
                        failed += 1
                        diagnostics.append(
                            GraphDiagnostic(
                                seed=seed,
                                direction=direction,
                                provider=self._provider(expander),
                                error=type(exc).__name__,
                            )
                        )
                        continue
                    for candidate in expanded:
                        if not self._in_scope(candidate, research_scope):
                            continue
                        key = candidate_identity(candidate)
                        returned.add(key)
                        provider = self._provider(expander, candidate)
                        path = {
                            "seed": seed,
                            "direction": direction,
                            "provider": provider,
                        }
                        if path not in graph_paths.setdefault(key, []):
                            graph_paths[key].append(path)
                        discovered[key] = merge_candidates(discovered.get(key), candidate)
                        edge = CitationEdge(
                            source_id=seed,
                            target_id=self._paper_id(candidate),
                            direction=direction,
                            provider=provider,
                            seed=seed,
                        )
                        if edge not in edges:
                            edges.append(edge)
                frontier_yields.append(StepYield(f"{seed} {direction}", len(returned),
                                                 len(returned - seen_before), failed))
        truncated = len(discovered) > maximum
        ranked = sorted(
            discovered.items(),
            key=lambda item: (
                -item[1].relevance_score,
                -item[1].citation_count,
                -item[1].year,
                item[0],
            ),
        )[:maximum]
        candidates = tuple(
            replace(
                candidate,
                provenance={
                    **candidate.provenance,
                    **(
                        {"query_passes": query_passes[key]}
                        if key in query_passes
                        else {}
                    ),
                    **(
                        {"graph_paths": graph_paths[key]}
                        if key in graph_paths
                        else {}
                    ),
                },
            )
            for key, candidate in ranked
        )
        included = {candidate_identity(candidate) for candidate in candidates}
        scope_years = research_scope.get("years")
        saturation = assess(
            passes=pass_yields,
            frontier=frontier_yields,
            candidates=candidates,
            routes={key: len(query_passes.get(key, ())) + len(graph_paths.get(key, ()))
                    for key in discovered},
            skipped_seeds=graph_bounds.skipped_seeds,
            maximum=maximum,
            truncated=truncated,
            scope_years=[int(year) for year in scope_years]
            if isinstance(scope_years, (list, tuple)) else (),
        )
        return ResearchDiscovery(
            candidates=candidates,
            edges=tuple(
                edge
                for edge in edges
                if any(
                    self._paper_id(candidate) == edge.target_id
                    and candidate_identity(candidate) in included
                    for candidate in candidates
                )
            ),
            diagnostics=tuple(diagnostics),
            graph_bounds=graph_bounds,
            saturation=saturation,
        )


class ResearchWorkflow:
    def __init__(
        self,
        *,
        discoverer: Callable[[ResearchPlan], Iterable[CandidateMetadata]],
        evidence_provider: Callable[[list[CandidateMetadata]], Iterable[EvidenceRecord]] | None = None,
        mineru_cache: MineruCache | None = None,
    ) -> None:
        self.discoverer = discoverer
        self.evidence_provider = evidence_provider
        self.mineru_cache = mineru_cache

    def parse_for_internal_analysis(self, pdf: Path) -> MineruResult:
        if self.mineru_cache is None:
            raise RuntimeError("temporary MinerU analysis cache is not configured")
        return self.mineru_cache.parse(pdf)

    def run(self, brief: dict, output: Path) -> ResearchWorkflowResult:
        plan = ResearchPlanner().build(brief)
        if isinstance(self.discoverer, ResearchDiscoverer):
            discovered = self.discoverer(
                plan,
                analysis=brief.get("analysis") or {},
                scope=brief.get("scope") or {},
            )
        else:
            discovered = self.discoverer(plan)
        candidates = list(discovered)
        evidence = list(self.evidence_provider(candidates)) if self.evidence_provider else []
        for record in evidence:
            record.validate()
        delivery = ResearchDelivery(output).write(
            brief=brief,
            plan=plan,
            candidates=candidates,
            evidence=evidence,
            graph_edges=list(getattr(discovered, "edges", ())),
            graph_diagnostics=list(getattr(discovered, "diagnostics", ())),
            graph_bounds=getattr(discovered, "graph_bounds", None),
            saturation=getattr(discovered, "saturation", None) or None,
        )
        saturation = getattr(discovered, "saturation", None) or {}
        return ResearchWorkflowResult(
            status="review_required",
            query_passes=len(plan.queries),
            delivery=delivery,
            saturation_signals=tuple(saturation.get("signals", ())),
            next_actions=tuple(saturation.get("next_actions", ())),
        )
