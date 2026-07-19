from acquire_research_papers.research.planner import ResearchPlanner


def gap_brief() -> dict:
    return {
        "schema_version": 1,
        "mode": "research",
        "question_type": "gap-analysis",
        "research_question": "Does LLM-guided evolutionary search already optimize this coupling?",
        "work_under_review": {
            "scenario": "MEC",
            "mechanism": "LLM-guided evolutionary computation",
            "decisions": ["offloading", "resource allocation"],
            "objectives": ["latency", "energy"],
            "constraints": ["queue stability"],
        },
        "claims": [],
        "seed_papers": ["10.1234/seed"],
        "scope": {},
        "delivery": {"write_narrative": False, "export_markdown": False},
    }


def test_gap_plan_contains_four_complementary_passes() -> None:
    plan = ResearchPlanner().build(gap_brief())
    assert [query.kind for query in plan.queries] == [
        "direct",
        "mechanism-decomposition",
        "citation-expansion",
        "falsification",
    ]


def test_gap_plan_uses_work_dimensions_and_seed_graph() -> None:
    plan = ResearchPlanner().build(gap_brief())
    decomposed = plan.queries[1].query
    assert "MEC" in decomposed
    assert "offloading" in decomposed
    assert "queue stability" in decomposed
    assert plan.graph_requests[0].seed == "10.1234/seed"
    assert plan.graph_requests[0].directions == ("references", "citations", "related")


def test_falsification_query_seeks_prior_and_equivalent_work() -> None:
    query = ResearchPlanner().build(gap_brief()).queries[-1]
    assert query.kind == "falsification"
    assert "prior" in query.query.casefold()
    assert "equivalent" in query.query.casefold()
