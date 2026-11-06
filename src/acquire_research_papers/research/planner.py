from __future__ import annotations

import re
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


def _joined(*values: str) -> str:
    return " ".join(value for value in values if value)


class ResearchPlanner:
    """Keyword searches for a research brief.

    Every query holds only terms from the brief: keyword search engines treat instruction
    words such as "references" or "counterexample" as search terms, so the citation graph is
    expanded separately (``graph_requests``) and falsification searches the same problem
    without the proposed mechanism. ``queries`` and ``synonyms`` in the brief add searches.
    """

    def build(self, brief: dict[str, Any]) -> ResearchPlan:
        question = str(brief["research_question"]).strip()
        work = brief.get("work_under_review") or {}
        scenario = str(work.get("scenario") or "").strip()
        mechanism = str(work.get("mechanism") or "").strip()
        decisions = _values(work, "decisions")
        objectives = _values(work, "objectives")
        constraints = _values(work, "constraints")
        dimensions_text = _joined(scenario, mechanism, *decisions, *objectives, *constraints)
        problem_text = _joined(scenario, *decisions, *objectives, *constraints)
        seeds = tuple(str(seed).strip() for seed in brief.get("seed_papers") or [] if str(seed).strip())

        planned = [
            ResearchQuery(
                kind="direct",
                query=_joined(question, scenario, mechanism),
                rationale="Search the user's exact research question and its closest terminology.",
            ),
            ResearchQuery(
                kind="mechanism-decomposition",
                query=dimensions_text or question,
                rationale=(
                    "Search scenario, mechanism, decisions, objectives, and constraints together."
                ),
            ),
            ResearchQuery(
                kind="core-terms",
                query=_joined(mechanism, scenario),
                rationale="Search the mechanism and scenario alone, without the question's "
                          "wording; the seeds' citation graph is expanded separately.",
            ),
            ResearchQuery(
                kind="falsification",
                query=problem_text,
                rationale="Search the same problem without the proposed mechanism, to find prior "
                          "or equivalent work that would falsify the proposed gap.",
            ),
            *(ResearchQuery(kind="brief-query", query=value,
                            rationale="A search written in the brief.")
              for value in _values(brief, "queries")),
            *(ResearchQuery(kind="synonym", query=value,
                            rationale="An alternative name for the studied topic, from the brief.")
              for value in _values(brief, "synonyms")),
        ]
        queries: list[ResearchQuery] = []
        seen: set[frozenset[str]] = set()
        for query in planned:
            # Keyword engines ignore word order, so the same words in another order are the
            # same search; an empty or repeated search adds nothing.
            key = frozenset(re.findall(r"\w+", query.query.casefold()))
            if key and key not in seen:
                seen.add(key)
                queries.append(query)
        graph_requests = tuple(
            GraphRequest(seed=seed, directions=("references", "citations", "related"))
            for seed in seeds
        )
        return ResearchPlan(
            question_type=str(brief["question_type"]),
            research_question=question,
            queries=tuple(queries),
            graph_requests=graph_requests,
        )
