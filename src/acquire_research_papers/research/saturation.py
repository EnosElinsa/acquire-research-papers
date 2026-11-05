"""Search saturation diagnostics for one research discovery run.

They record how many new papers each query pass and each citation-graph step still added, how
the candidates spread over years, and which candidates rest on a single search route. A run
whose last steps added few new papers is saturated only within its own queries and graph
bounds; these numbers never estimate recall of the literature.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from acquire_research_papers.discovery.contracts import CandidateMetadata
from acquire_research_papers.discovery.coordinator import candidate_identity

SCOPE_NOTE = ("Describes this run's queries and citation-graph bounds only; it is not an "
              "estimate of how much of the literature was found.")
# A step still "growing" when at least this share, and at least MIN_NEW, of its results are new.
GROWING_SHARE = 0.3
MIN_NEW = 3
RECENT_YEARS = 3
HIGHLY_CITED = 100
BOUNDARY_LIMIT = 20


@dataclass(frozen=True)
class StepYield:
    """In-scope results of one query pass or one (seed, direction) graph step."""

    label: str
    returned: int
    new: int
    failed_providers: int = 0

    @property
    def new_share(self) -> float:
        return round(self.new / self.returned, 3) if self.returned else 0.0

    def growing(self) -> bool:
        return self.new >= MIN_NEW and self.new_share >= GROWING_SHARE

    def to_dict(self) -> dict[str, Any]:
        return {"step": self.label, "returned": self.returned, "new": self.new,
                "new_share": self.new_share, "failed_providers": self.failed_providers}


def _total(steps: Iterable[StepYield]) -> dict[str, Any]:
    steps = list(steps)
    returned = sum(step.returned for step in steps)
    new = sum(step.new for step in steps)
    return {"returned": returned, "new": new,
            "new_share": round(new / returned, 3) if returned else 0.0}


def _last_with_results(steps: Sequence[StepYield]) -> StepYield | None:
    return next((step for step in reversed(steps) if step.returned), None)


def assess(
    *,
    passes: Sequence[StepYield],
    frontier: Sequence[StepYield],
    candidates: Sequence[CandidateMetadata],
    routes: dict[str, int],  # candidate identity -> distinct query passes and graph paths
    skipped_seeds: Sequence[str],
    maximum: int,
    truncated: bool,
    scope_years: Sequence[int] = (),
) -> dict[str, Any]:
    """The saturation record written next to the research plan."""
    years = Counter(candidate.year for candidate in candidates if candidate.year)
    newest = max(scope_years) if scope_years else max(years, default=0)
    recent = sum(count for year, count in years.items() if newest and year > newest - RECENT_YEARS)
    earlier = sum(years.values()) - recent
    boundary = []
    single_route = no_abstract = 0
    for candidate in candidates:
        reasons = []
        if routes.get(candidate_identity(candidate), 0) <= 1:
            reasons.append("single_route")
            single_route += 1
        if not candidate.abstract.strip():
            reasons.append("no_abstract")
            no_abstract += 1
        if reasons:
            boundary.append({"key": candidate.key, "title": candidate.title,
                             "year": candidate.year, "reasons": reasons})
    signals: list[str] = []
    actions: list[dict[str, str]] = []
    last_pass = _last_with_results(passes)
    if last_pass is not None and last_pass.growing():
        signals.append("search_still_growing")
        actions.append({"action": "broaden_queries", "reason": (
            f"the {last_pass.label} pass still added {last_pass.new} new papers "
            f"({last_pass.new_share:.0%} of its results); add synonyms, older terminology, or "
            "venue names to the brief and rerun discovery in a new directory")})
    last_step = _last_with_results(frontier)
    if last_step is not None and last_step.growing():
        signals.append("citation_frontier_growing")
        actions.append({"action": "widen_graph", "reason": (
            f"the last citation-graph step ({last_step.label}) still added {last_step.new} new "
            "papers; raise analysis.graph_seed_limit or analysis.graph_neighbors_per_direction")})
    if skipped_seeds:
        signals.append("seeds_not_expanded")
        actions.append({"action": "expand_seeds", "reason": (
            f"{len(skipped_seeds)} candidate seeds were not expanded because of "
            "analysis.graph_seed_limit")})
    if truncated:
        signals.append("candidate_limit_reached")
        actions.append({"action": "review_ranking", "reason": (
            f"the candidate list reached its maximum of {maximum}; lower-ranked papers were cut")})
    if any(step.failed_providers for step in (*passes, *frontier)):
        signals.append("provider_failures")
        actions.append({"action": "rerun_later", "reason": (
            "some search or graph providers failed; their results are missing from this run")})
    if candidates and not recent:
        signals.append("no_recent_work")
        actions.append({"action": "search_recent_work", "reason": (
            f"no candidate is from the last {RECENT_YEARS} scope years; add current terminology "
            "or recent venues to the brief")})
    if candidates and not earlier:
        signals.append("no_earlier_work")
        actions.append({"action": "search_older_work", "reason": (
            f"every candidate is from the last {RECENT_YEARS} years; older or classic work may "
            "use different terminology")})
    if not {"search_still_growing", "citation_frontier_growing", "seeds_not_expanded",
            "candidate_limit_reached", "provider_failures"} & set(signals):
        signals.append("stable_within_bounds")
    return {
        "schema_version": 1,
        "scope_note": SCOPE_NOTE,
        "signals": signals,
        "next_actions": actions,
        "query_passes": {"steps": [step.to_dict() for step in passes], **_total(passes)},
        "citation_frontier": {"steps": [step.to_dict() for step in frontier], **_total(frontier),
                              "skipped_seeds": list(skipped_seeds)},
        "coverage": {
            "candidates": len(candidates),
            "years": {str(year): years[year] for year in sorted(years)},
            "recent_years": RECENT_YEARS,
            "recent": recent,
            "earlier": earlier,
            "highly_cited": sum(candidate.citation_count >= HIGHLY_CITED for candidate in candidates),
            "with_abstract": len(candidates) - no_abstract,
        },
        "boundary_papers": {"single_route": single_route, "no_abstract": no_abstract,
                            "listed": boundary[:BOUNDARY_LIMIT]},
    }


def summary_lines(record: dict[str, Any]) -> list[str]:
    """Markdown lines for the evidence report."""
    passes = record.get("query_passes", {})
    frontier = record.get("citation_frontier", {})
    coverage = record.get("coverage", {})
    lines = [f"Signals: {', '.join(f'`{signal}`' for signal in record.get('signals', [])) or 'none'}.",
             "", str(record.get("scope_note", SCOPE_NOTE)), ""]
    for step in passes.get("steps", []):
        lines.append(f"- Query pass `{step['step']}`: {step['returned']} in scope, "
                     f"{step['new']} new ({step['new_share']:.0%}).")
    lines.append(f"- Citation frontier: {frontier.get('returned', 0)} in scope, "
                 f"{frontier.get('new', 0)} new; {len(frontier.get('skipped_seeds', []))} "
                 "seeds not expanded.")
    lines.append(f"- Years: {coverage.get('recent', 0)} candidates from the last "
                 f"{coverage.get('recent_years', RECENT_YEARS)} years, {coverage.get('earlier', 0)} "
                 f"earlier; {coverage.get('highly_cited', 0)} cited at least {HIGHLY_CITED} times.")
    boundary = record.get("boundary_papers", {})
    lines.append(f"- Boundary papers: {boundary.get('single_route', 0)} found by a single route, "
                 f"{boundary.get('no_abstract', 0)} without an abstract.")
    for action in record.get("next_actions", []):
        lines.append(f"- Next: `{action['action']}`: {action['reason']}.")
    return lines
