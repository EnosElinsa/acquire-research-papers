import json
from pathlib import Path

from acquire_research_papers.discovery.corpus import CandidateMetadata
from acquire_research_papers.research.planner import ResearchPlanner
from acquire_research_papers.research.saturation import StepYield, assess, summary_lines
from acquire_research_papers.research.workflow import ResearchDiscoverer, ResearchWorkflow

BRIEF = {
    "schema_version": 1,
    "mode": "research",
    "question_type": "gap-analysis",
    "research_question": "Has prior work solved this coupling?",
    "work_under_review": {"scenario": "MEC", "mechanism": "LLM search"},
}


def paper(key: str, year: int = 2025, *, abstract: str = "Lead.", citations: int = 0):
    return CandidateMetadata(
        key=key, title=f"Paper {key}", year=year, venue="Test", relevance_score=0.5,
        hard_gates_passed=True, evidence_fields=("title",), doi=f"10.1000/{key}",
        abstract=abstract, citation_count=citations,
    )


def record(passes, frontier=(), candidates=(paper("a", 2019), paper("b")), **options):
    return assess(passes=passes, frontier=frontier, candidates=list(candidates),
                  routes=options.pop("routes", {}), skipped_seeds=options.pop("skipped", ()),
                  maximum=100, truncated=options.pop("truncated", False), **options)


def test_a_last_pass_that_still_adds_many_papers_asks_for_broader_queries() -> None:
    result = record([StepYield("direct", 10, 10), StepYield("falsification", 8, 5)])

    assert "search_still_growing" in result["signals"]
    assert result["next_actions"][0]["action"] == "broaden_queries"
    assert result["query_passes"]["steps"][1] == {
        "step": "falsification", "returned": 8, "new": 5, "new_share": 0.625,
        "failed_providers": 0}
    assert "not an estimate" in result["scope_note"]


def test_a_run_whose_last_steps_add_nothing_is_stable_only_within_its_bounds() -> None:
    result = record([StepYield("direct", 10, 10), StepYield("falsification", 6, 0)],
                    frontier=[StepYield("10.1000/a references", 5, 0)])

    assert result["signals"] == ["stable_within_bounds"]
    assert result["next_actions"] == []


def test_a_few_new_papers_in_a_small_step_are_not_called_growth() -> None:
    # Two new out of two is a high share but below the minimum count.
    assert record([StepYield("falsification", 2, 2)])["signals"] == ["stable_within_bounds"]


def test_frontier_growth_skipped_seeds_truncation_and_failures_are_flagged() -> None:
    result = record([StepYield("direct", 4, 4, failed_providers=1)],
                    frontier=[StepYield("10.1000/a citations", 10, 6)],
                    skipped=("10.1000/b",), truncated=True)

    assert set(result["signals"]) >= {"citation_frontier_growing", "seeds_not_expanded",
                                      "candidate_limit_reached", "provider_failures"}
    assert "stable_within_bounds" not in result["signals"]
    assert result["citation_frontier"]["skipped_seeds"] == ["10.1000/b"]


def test_year_coverage_flags_a_candidate_set_with_only_recent_work() -> None:
    result = record([StepYield("direct", 2, 2)],
                    candidates=[paper("a", 2025, citations=150), paper("b", 2026, abstract="")],
                    scope_years=[2024, 2025, 2026])

    assert result["coverage"]["recent"] == 2 and result["coverage"]["earlier"] == 0
    assert result["coverage"]["highly_cited"] == 1
    assert "no_earlier_work" in result["signals"]
    assert result["boundary_papers"]["no_abstract"] == 1


def test_the_discoverer_counts_new_papers_per_pass_and_graph_step() -> None:
    per_pass = {"direct": ["a", "b"], "mechanism-decomposition": ["b", "c"],
                "citation-expansion": ["c"], "falsification": ["a"]}
    plan = ResearchPlanner().build(BRIEF)
    kinds = iter(query.kind for query in plan.queries)

    def searcher(_query: str, _rows: int):
        return tuple(paper(key) for key in per_pass[next(kinds)])

    def expander(seed: str, direction: str, _limit: int):
        return (paper("d"),) if direction == "references" else ()

    discovery = ResearchDiscoverer([searcher], graph_expanders=[expander], graph_seed_limit=1)(plan)

    steps = discovery.saturation["query_passes"]["steps"]
    assert [(step["step"], step["returned"], step["new"]) for step in steps] == [
        ("direct", 2, 2), ("mechanism-decomposition", 2, 1), ("citation-expansion", 1, 0),
        ("falsification", 1, 0)]
    frontier = discovery.saturation["citation_frontier"]
    assert [(step["returned"], step["new"]) for step in frontier["steps"]] == [(1, 1), (0, 0), (0, 0)]
    assert frontier["skipped_seeds"] == ["10.1000/b", "10.1000/c"]
    # "d" came only from the graph and "c" from two passes; "a" and "b" from two passes each.
    assert discovery.saturation["boundary_papers"]["single_route"] == 1


def test_the_workflow_writes_the_record_and_names_it_in_the_run_manifest(tmp_path: Path) -> None:
    workflow = ResearchWorkflow(discoverer=ResearchDiscoverer(
        [lambda _query, _rows: (paper("a", 2024),)], graph_seed_limit=0))

    result = workflow.run(BRIEF, tmp_path / "run")

    saturation = json.loads((tmp_path / "run" / "search-saturation.json").read_text(encoding="utf-8"))
    assert saturation["coverage"]["candidates"] == 1
    run = json.loads((tmp_path / "run" / "research-run.json").read_text(encoding="utf-8"))
    assert run["search_saturation"] == "search-saturation.json"
    assert result.saturation_signals == tuple(saturation["signals"])
    assert any("Query pass `direct`" in line for line in summary_lines(saturation))
