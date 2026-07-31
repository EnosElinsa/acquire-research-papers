from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from acquire_research_papers.discovery.corpus import CandidateMetadata
from acquire_research_papers.discovery.coordinator import candidate_identity, merge_candidates
from acquire_research_papers.mineru import MineruCache, MineruResult
from acquire_research_papers.research.delivery import ResearchDelivery, ResearchDeliveryResult
from acquire_research_papers.research.evidence import EvidenceRecord
from acquire_research_papers.research.planner import ResearchPlan, ResearchPlanner


@dataclass(frozen=True)
class ResearchWorkflowResult:
    status: str
    query_passes: int
    delivery: ResearchDeliveryResult


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

    def __iter__(self) -> Iterator[CandidateMetadata]:
        return iter(self.candidates)

    def __len__(self) -> int:
        return len(self.candidates)

    def __getitem__(self, index):
        return self.candidates[index]


class ResearchDiscoverer:
    def __init__(
        self,
        searchers: Iterable[Callable[[str, int], Iterable[CandidateMetadata]]],
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

        def normalized(value: object) -> str:
            return " ".join(re.findall(r"\w+", str(value).casefold()))

        venues = scope.get("venues")
        if isinstance(venues, (list, tuple)) and venues:
            allowed = {normalized(venue) for venue in venues}
            if normalized(candidate.venue) not in allowed:
                return False
        haystack = normalized(
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
            if not any(normalized(term) in haystack for term in include_terms):
                return False
        exclude_terms = scope.get("exclude_terms")
        if isinstance(exclude_terms, (list, tuple)) and any(
            normalized(term) in haystack for term in exclude_terms
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
        settings = analysis or {}
        research_scope = scope or {}
        graph_limit = int(settings.get("graph_neighbors_per_direction", self.graph_limit))
        graph_seed_limit = int(settings.get("graph_seed_limit", self.graph_seed_limit))
        discovered: dict[str, CandidateMetadata] = {}
        query_passes: dict[str, list[str]] = {}
        diagnostics: list[GraphDiagnostic] = []
        for query in plan.queries:
            for searcher in self.searchers:
                try:
                    searched = tuple(searcher(query.query, self.rows_per_query))
                except Exception as exc:
                    diagnostics.append(
                        GraphDiagnostic(
                            seed="",
                            direction=f"search:{query.kind}",
                            provider=self._provider(searcher),
                            error=type(exc).__name__,
                        )
                    )
                    continue
                for candidate in searched:
                    if not self._in_scope(candidate, research_scope):
                        continue
                    key = candidate_identity(candidate)
                    discovered[key] = merge_candidates(discovered.get(key), candidate)
                    passes = query_passes.setdefault(key, [])
                    if query.kind not in passes:
                        passes.append(query.kind)
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
        for seed, directions in graph_requests:
            for direction in directions:
                for expander in self.graph_expanders:
                    try:
                        expanded = tuple(expander(seed, direction, graph_limit))
                    except Exception as exc:
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
        ranked = sorted(
            discovered.items(),
            key=lambda item: (
                -item[1].relevance_score,
                -item[1].citation_count,
                -item[1].year,
                item[0],
            ),
        )[: self.maximum]
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
        )
        return ResearchWorkflowResult(
            status="review_required",
            query_passes=len(plan.queries),
            delivery=delivery,
        )
