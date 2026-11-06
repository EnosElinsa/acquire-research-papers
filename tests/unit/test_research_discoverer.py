from acquire_research_papers.discovery.corpus import CandidateMetadata
from acquire_research_papers.research.planner import ResearchPlanner
from acquire_research_papers.research.workflow import ResearchDiscoverer


def test_research_discoverer_runs_four_passes_and_deduplicates_doi() -> None:
    calls = []

    def searcher(query: str, rows: int):
        calls.append((query, rows))
        return (
            CandidateMetadata(
                key=f"source-{len(calls)}",
                title="Same Paper",
                year=2026,
                venue="Test",
                relevance_score=0.7 + len(calls) / 100,
                hard_gates_passed=True,
                evidence_fields=("title", "abstract"),
                doi="10.1000/same",
                abstract="Evidence lead only.",
            ),
        )

    plan = ResearchPlanner().build(
        {
            "schema_version": 1,
            "mode": "research",
            "question_type": "gap-analysis",
            "research_question": "Has prior work solved this coupling?",
            "work_under_review": {"scenario": "MEC", "mechanism": "LLM search"},
        }
    )
    candidates = ResearchDiscoverer([searcher], rows_per_query=20)(plan)
    # With only a scenario and a mechanism, the core-terms search repeats the decomposition's
    # words and is dropped.
    assert len(calls) == 3
    assert all(rows == 20 for _, rows in calls)
    assert len(candidates) == 1
    assert candidates[0].doi == "10.1000/same"
    assert candidates[0].relevance_score == 0.73
    assert candidates[0].provenance["query_passes"] == [
        "direct",
        "mechanism-decomposition",
        "falsification",
    ]


def test_the_brief_sets_rows_per_query_and_the_candidate_limit() -> None:
    calls = []

    def searcher(query: str, rows: int):
        calls.append(rows)
        return tuple(
            CandidateMetadata(key=f"{query}-{index}", title=f"Paper {query} {index}", year=2025,
                              venue="Test", relevance_score=0.5, hard_gates_passed=True,
                              evidence_fields=("title",), doi=f"10.1000/{len(calls)}.{index}")
            for index in range(rows))

    plan = ResearchPlanner().build({
        "schema_version": 1, "mode": "research", "question_type": "similar-work",
        "research_question": "closest work", "queries": ["second search"]})
    candidates = ResearchDiscoverer([searcher], graph_seed_limit=0)(
        plan, analysis={"rows_per_query": 7, "max_candidates": 9})
    assert calls == [7, 7]
    assert len(candidates) == 9
    assert "candidate_limit_reached" in candidates.saturation["signals"]


def test_research_venue_scope_unescapes_entities_and_accepts_presets_and_issns() -> None:
    def paper(key: str, venue: str, issn: tuple[str, ...] = ()) -> CandidateMetadata:
        return CandidateMetadata(key=key, title=f"Survey {key}", year=2025, venue=venue,
                                 relevance_score=0.5, hard_gates_passed=True,
                                 evidence_fields=("title",), doi=f"10.1109/{key}",
                                 provenance={"source": "crossref", "issn": issn})

    in_scope = ResearchDiscoverer._in_scope
    comst = {"venues": ["IEEE Communications Surveys & Tutorials"]}
    assert in_scope(paper("a", "IEEE Communications Surveys &amp; Tutorials"), comst)
    assert in_scope(paper("b", "IEEE Robotics &amp; Automation Magazine"), {"venues": ["RAM"]})
    assert in_scope(paper("c", "IEEE Trans. Robot.", ("1941-0468",)), {"venues": ["T-RO"]})
    assert in_scope(paper("d", "Some Abbreviation", ("1552-3098",)), {"venues": ["1552-3098"]})
    assert not in_scope(paper("e", "IEEE Transactions on Mobile Computing"),
                        {"venues": ["T-RO"]})


def test_research_discoverer_expands_citation_graph_and_records_edges() -> None:
    searched = CandidateMetadata(
        key="seed-paper",
        title="Closest Search Hit",
        year=2025,
        venue="Test",
        relevance_score=0.9,
        hard_gates_passed=True,
        evidence_fields=("title", "abstract"),
        doi="10.1000/seed",
        abstract="A close abstract.",
    )
    cited = CandidateMetadata(
        key="cited-paper",
        title="Earlier Mechanism",
        year=2022,
        venue="Test",
        relevance_score=0.0,
        hard_gates_passed=True,
        evidence_fields=("title", "abstract"),
        doi="10.1000/cited",
        abstract="The earlier mechanism.",
        provenance={"source": "semantic-scholar"},
    )
    calls: list[tuple[str, str, int]] = []

    def graph_expander(seed: str, direction: str, limit: int):
        calls.append((seed, direction, limit))
        return (cited,) if direction == "references" else ()

    plan = ResearchPlanner().build(
        {
            "schema_version": 1,
            "mode": "research",
            "question_type": "gap-analysis",
            "research_question": "Has prior work solved this coupling?",
            "seed_papers": ["10.1000/seed"],
        }
    )
    discovery = ResearchDiscoverer(
        [lambda _query, _rows: (searched,)],
        graph_expanders=[graph_expander],
        graph_limit=10,
    )(plan)

    assert {candidate.doi for candidate in discovery} == {
        "10.1000/seed",
        "10.1000/cited",
    }
    assert calls == [
        ("10.1000/seed", "references", 10),
        ("10.1000/seed", "citations", 10),
        ("10.1000/seed", "related", 10),
    ]
    assert discovery.edges[0].direction == "references"
    assert discovery.edges[0].source_id == "10.1000/seed"
    assert discovery.edges[0].target_id == "10.1000/cited"
    graph_candidate = next(item for item in discovery if item.doi == "10.1000/cited")
    assert graph_candidate.provenance["graph_paths"] == [
        {
            "seed": "10.1000/seed",
            "direction": "references",
            "provider": "semantic-scholar",
        }
    ]


def test_research_discoverer_uses_top_doi_hit_as_graph_seed_without_explicit_seed() -> None:
    candidate = CandidateMetadata(
        key="paper",
        title="Top Hit",
        year=2025,
        venue="Test",
        relevance_score=0.9,
        hard_gates_passed=True,
        evidence_fields=("title",),
        doi="10.1000/top",
    )
    calls: list[tuple[str, str, int]] = []

    def graph_expander(seed: str, direction: str, limit: int):
        calls.append((seed, direction, limit))
        return ()

    plan = ResearchPlanner().build(
        {
            "schema_version": 1,
            "mode": "research",
            "question_type": "similar-work",
            "research_question": "What is the closest prior work?",
        }
    )
    ResearchDiscoverer(
        [lambda _query, _rows: (candidate,)],
        graph_expanders=[graph_expander],
    )(
        plan,
        analysis={"graph_seed_limit": 1, "graph_neighbors_per_direction": 7},
    )

    assert calls == [
        ("10.1000/top", "references", 7),
        ("10.1000/top", "citations", 7),
        ("10.1000/top", "related", 7),
    ]


def test_research_discoverer_caps_explicit_graph_seeds() -> None:
    calls: list[tuple[str, str, int]] = []

    def graph_expander(seed: str, direction: str, limit: int):
        calls.append((seed, direction, limit))
        return ()

    plan = ResearchPlanner().build(
        {
            "schema_version": 1,
            "mode": "research",
            "question_type": "similar-work",
            "research_question": "What is the closest prior work?",
            "seed_papers": ["10.1000/first", "10.1000/second"],
        }
    )
    result = ResearchDiscoverer(
        [],
        graph_expanders=[graph_expander],
    )(plan, analysis={"graph_seed_limit": 1})

    assert {seed for seed, _, _ in calls} == {"10.1000/first"}
    assert result.graph_bounds.requested_seeds == (
        "10.1000/first",
        "10.1000/second",
    )
    assert result.graph_bounds.expanded_seeds == ("10.1000/first",)
    assert result.graph_bounds.skipped_seeds == ("10.1000/second",)


def test_research_discoverer_keeps_other_sources_when_optional_search_fails() -> None:
    candidate = CandidateMetadata(
        key="paper",
        title="Recovered Hit",
        year=2025,
        venue="Test",
        relevance_score=0.8,
        hard_gates_passed=True,
        evidence_fields=("title",),
        doi="10.1000/recovered",
    )

    def unavailable(_query: str, _rows: int):
        raise RuntimeError("secret details must not be copied")

    plan = ResearchPlanner().build(
        {
            "schema_version": 1,
            "mode": "research",
            "question_type": "similar-work",
            "research_question": "What is the closest prior work?",
        }
    )
    result = ResearchDiscoverer(
        [unavailable, lambda _query, _rows: (candidate,)],
        graph_seed_limit=0,
    )(plan)

    assert len(result) == 1
    # A brief with only a question plans one search; the failing source fails it once.
    assert len(result.diagnostics) == len(plan.queries) == 1
    assert {item.error for item in result.diagnostics} == {"RuntimeError"}
    assert all("secret" not in repr(item) for item in result.diagnostics)


def test_research_discoverer_applies_explicit_year_venue_and_term_scope() -> None:
    candidates = (
        CandidateMetadata(
            key="keep",
            title="LLM-guided evolutionary scheduling",
            year=2025,
            venue="Target Journal",
            relevance_score=0.9,
            hard_gates_passed=True,
            evidence_fields=("title", "abstract"),
            doi="10.1000/keep",
            abstract="Joint optimization of two decisions.",
        ),
        CandidateMetadata(
            key="old",
            title="LLM-guided evolutionary scheduling",
            year=2021,
            venue="Target Journal",
            relevance_score=0.9,
            hard_gates_passed=True,
            evidence_fields=("title", "abstract"),
            doi="10.1000/old",
            abstract="Joint optimization.",
        ),
        CandidateMetadata(
            key="excluded",
            title="LLM-guided evolutionary survey",
            year=2025,
            venue="Target Journal",
            relevance_score=0.9,
            hard_gates_passed=True,
            evidence_fields=("title", "abstract"),
            doi="10.1000/excluded",
            abstract="A survey.",
        ),
    )
    plan = ResearchPlanner().build(
        {
            "schema_version": 1,
            "mode": "research",
            "question_type": "similar-work",
            "research_question": "What is the closest prior work?",
        }
    )

    result = ResearchDiscoverer(
        [lambda _query, _rows: candidates],
        graph_seed_limit=0,
    )(
        plan,
        scope={
            "years": [2025],
            "venues": ["Target Journal"],
            "include_terms": ["evolutionary"],
            "exclude_terms": ["survey"],
        },
    )

    assert [candidate.doi for candidate in result] == ["10.1000/keep"]


def test_scoped_searchers_receive_the_brief_scope_and_results_are_checked_again() -> None:
    from acquire_research_papers.research.workflow import ScopedSearcher

    received = {}

    def make(name: str):
        def search(query: str, rows: int, request):
            received[name] = request
            return (
                CandidateMetadata(key=f"{name}-ieee", title="Path Planning: A Survey",
                                  year=2025, venue="IEEE Transactions on Robotics",
                                  relevance_score=0.6, hard_gates_passed=True,
                                  evidence_fields=("title",), doi=f"10.1109/{name}",
                                  provenance={"source": name, "issn": ("1552-3098",)}),
                CandidateMetadata(key=f"{name}-other", title="Path Planning: A Survey",
                                  year=2025, venue="IEEE Transactions on Robotics",
                                  relevance_score=0.6, hard_gates_passed=True,
                                  evidence_fields=("title",), doi=f"10.1016/{name}",
                                  provenance={"source": name, "issn": ("1552-3098",)}),
            )
        return search

    plan = ResearchPlanner().build({"schema_version": 1, "mode": "research",
                                    "question_type": "related-work",
                                    "research_question": "path planning surveys"})
    scope = {"years": [2024, 2025], "venues": ["T-RO"], "publication_types": ["review"],
             "doi_prefixes": ["10.1109"], "title_terms": ["planning"]}
    candidates = ResearchDiscoverer(
        [ScopedSearcher("crossref", make("crossref")),
         ScopedSearcher("semantic-scholar", make("semantic"), issn_filter=False)],
        graph_seed_limit=0)(plan, scope=scope)

    crossref, semantic = received["crossref"], received["semantic"]
    assert crossref.years == (2024, 2025)
    assert crossref.query_filters.issns == ("1552-3098", "1941-0468")
    assert crossref.query_filters.doi_prefixes == ("10.1109",)
    # Without an ISSN filter the source searches all journals; the scope check filters.
    assert semantic.query_filters.issns == () and semantic.years == (2024, 2025)
    assert sorted(c.doi for c in candidates) == ["10.1109/crossref", "10.1109/semantic"]


def test_the_scope_check_applies_type_doi_prefix_and_title_terms() -> None:
    def paper(title: str, doi: str) -> CandidateMetadata:
        return CandidateMetadata(key=doi, title=title, year=2025, venue="V",
                                 relevance_score=0.5, hard_gates_passed=True,
                                 evidence_fields=("title",), doi=doi)

    scope = {"publication_types": ["review"], "doi_prefixes": ["10.1109"],
             "title_terms": ["path planning|navigation"]}
    in_scope = ResearchDiscoverer._in_scope
    assert in_scope(paper("Robot Navigation: A Review", "10.1109/a"), scope)
    assert not in_scope(paper("Robot Navigation: A Review", "10.1016/a"), scope)
    assert not in_scope(paper("Robot Navigation With Learned Maps", "10.1109/b"), scope)
    assert not in_scope(paper("Grasping: A Survey", "10.1109/c"), scope)
