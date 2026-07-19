from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
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
