from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ResearchQuery:
    kind: str
    query: str
    rationale: str


@dataclass(frozen=True)
class GraphRequest:
    seed: str
    directions: tuple[str, ...]


@dataclass(frozen=True)
class ResearchPlan:
    question_type: str
    research_question: str
    queries: tuple[ResearchQuery, ...]
    graph_requests: tuple[GraphRequest, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _values(record: dict[str, Any], key: str) -> list[str]:
    value = record.get(key) or []
    return [str(item).strip() for item in value if str(item).strip()]


class ResearchPlanner:
    def build(self, brief: dict[str, Any]) -> ResearchPlan:
        question = str(brief["research_question"]).strip()
        work = brief.get("work_under_review") or {}
        scenario = str(work.get("scenario") or "").strip()
        mechanism = str(work.get("mechanism") or "").strip()
        decisions = _values(work, "decisions")
        objectives = _values(work, "objectives")
        constraints = _values(work, "constraints")
        dimensions = [scenario, mechanism, *decisions, *objectives, *constraints]
        dimensions_text = " ".join(value for value in dimensions if value)
        seeds = tuple(str(seed).strip() for seed in brief.get("seed_papers") or [] if str(seed).strip())

        queries = (
            ResearchQuery(
                kind="direct",
                query=" ".join(value for value in (question, scenario, mechanism) if value),
                rationale="Search the user's exact research question and its closest terminology.",
            ),
            ResearchQuery(
                kind="mechanism-decomposition",
                query=dimensions_text or question,
                rationale=(
                    "Search scenario, mechanism, decisions, objectives, and constraints separately and in "
                    "pairwise combinations."
                ),
            ),
            ResearchQuery(
                kind="citation-expansion",
                query=(
                    f"references citations related works for {' '.join(seeds)}"
                    if seeds
                    else f"references citations related works for {mechanism or question}"
                ),
                rationale="Expand backward citations, forward citations, and graph-nearest papers.",
            ),
            ResearchQuery(
                kind="falsification",
                query=(
                    f"prior work equivalent method counterexample already solves {dimensions_text or question}"
                ),
                rationale="Actively seek prior or equivalent work that would falsify the proposed gap.",
            ),
        )
        graph_requests = tuple(
            GraphRequest(seed=seed, directions=("references", "citations", "related"))
            for seed in seeds
        )
        return ResearchPlan(
            question_type=str(brief["question_type"]),
            research_question=question,
            queries=queries,
            graph_requests=graph_requests,
        )
