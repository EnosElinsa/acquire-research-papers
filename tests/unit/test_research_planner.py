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
        "core-terms",
        "falsification",
    ]


def test_queries_hold_only_terms_from_the_brief() -> None:
    # Keyword engines search instruction words too; the citation graph is expanded separately.
    for query in ResearchPlanner().build(gap_brief()).queries:
        words = set(query.query.casefold().split())
        assert not words & {"references", "citations", "counterexample", "equivalent",
                            "solves", "works"}, query


def test_gap_plan_uses_work_dimensions_and_seed_graph() -> None:
    plan = ResearchPlanner().build(gap_brief())
    decomposed = plan.queries[1].query
    assert "MEC" in decomposed
    assert "offloading" in decomposed
    assert "queue stability" in decomposed
    assert plan.graph_requests[0].seed == "10.1234/seed"
    assert plan.graph_requests[0].directions == ("references", "citations", "related")


def test_falsification_searches_the_same_problem_without_the_mechanism() -> None:
    query = ResearchPlanner().build(gap_brief()).queries[-1]
    assert query.kind == "falsification"
    assert query.query == "MEC offloading resource allocation latency energy queue stability"
    assert "evolutionary" not in query.query.casefold()


def test_brief_queries_and_synonyms_add_searches_and_repeats_are_dropped() -> None:
    # The second query repeats the core-terms search apart from case and spacing.
    brief = {**gap_brief(), "queries": ["joint offloading LLM evolutionary",
                                        "llm-guided  evolutionary computation MEC"],
             "synonyms": ["edge computing task offloading", "  "]}
    plan = ResearchPlanner().build(brief)
    assert [(query.kind, query.query) for query in plan.queries[4:]] == [
        ("brief-query", "joint offloading LLM evolutionary"),
        ("synonym", "edge computing task offloading"),
    ]


def test_a_question_alone_yields_one_search() -> None:
    plan = ResearchPlanner().build({"schema_version": 1, "mode": "research",
                                    "question_type": "similar-work",
                                    "research_question": "What is the closest prior work?"})
    assert [query.kind for query in plan.queries] == ["direct"]
