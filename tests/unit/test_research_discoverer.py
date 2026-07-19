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
    assert len(calls) == 4
    assert all(rows == 20 for _, rows in calls)
    assert len(candidates) == 1
    assert candidates[0].doi == "10.1000/same"
    assert candidates[0].relevance_score == 0.74
    assert candidates[0].provenance["query_passes"] == [
        "direct",
        "mechanism-decomposition",
        "citation-expansion",
        "falsification",
    ]
