from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import Path

from acquire_research_papers.discovery.corpus import CandidateMetadata
from acquire_research_papers.mineru import MineruCache, MineruResult
from acquire_research_papers.research.delivery import ResearchDelivery, ResearchDeliveryResult
from acquire_research_papers.research.evidence import EvidenceRecord
from acquire_research_papers.research.planner import ResearchPlan, ResearchPlanner


@dataclass(frozen=True)
class ResearchWorkflowResult:
    status: str
    query_passes: int
    delivery: ResearchDeliveryResult


class ResearchDiscoverer:
    def __init__(
        self,
        searchers: Iterable[Callable[[str, int], Iterable[CandidateMetadata]]],
        *,
        rows_per_query: int = 25,
        maximum: int = 100,
    ) -> None:
        self.searchers = tuple(searchers)
        self.rows_per_query = rows_per_query
        self.maximum = maximum

    def __call__(self, plan: ResearchPlan) -> tuple[CandidateMetadata, ...]:
        discovered: dict[str, CandidateMetadata] = {}
        query_passes: dict[str, list[str]] = {}
        for query in plan.queries:
            for searcher in self.searchers:
                for candidate in searcher(query.query, self.rows_per_query):
                    key = candidate.doi or candidate.key or (
                        f"{candidate.title.casefold()}|{candidate.year}"
                    )
                    if not key:
                        continue
                    previous = discovered.get(key)
                    if previous is None or candidate.relevance_score > previous.relevance_score:
                        discovered[key] = candidate
                    passes = query_passes.setdefault(key, [])
                    if query.kind not in passes:
                        passes.append(query.kind)
        ranked = sorted(
            discovered.items(),
            key=lambda item: (
                -item[1].relevance_score,
                -item[1].citation_count,
                -item[1].year,
                item[0],
            ),
        )[: self.maximum]
        return tuple(
            replace(
                candidate,
                provenance={
                    **candidate.provenance,
                    "query_passes": query_passes[key],
                },
            )
            for key, candidate in ranked
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
        candidates = list(self.discoverer(plan))
        evidence = list(self.evidence_provider(candidates)) if self.evidence_provider else []
        for record in evidence:
            record.validate()
        delivery = ResearchDelivery(output).write(
            brief=brief,
            plan=plan,
            candidates=candidates,
            evidence=evidence,
        )
        return ResearchWorkflowResult(
            status="planned",
            query_passes=len(plan.queries),
            delivery=delivery,
        )
