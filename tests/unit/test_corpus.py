from acquire_research_papers.discovery.corpus import (
    CandidateMetadata,
    CorpusPlanner,
    ScreeningGate,
)
from acquire_research_papers.models import PaperStatus


def candidate(
    key: str,
    year: int,
    score: float,
    *,
    venue: str = "Test",
    hard_gates: bool = True,
) -> CandidateMetadata:
    return CandidateMetadata(
        key,
        key,
        year,
        venue,
        score,
        hard_gates,
        ("title", "abstract"),
    )


def test_corpus_prioritizes_recent_and_stops_at_preferred() -> None:
    spec = {
        "target": {"preferred": 3, "minimum": 2, "maximum": 4},
        "scope": {"years": {"include": [2026, 2025, 2024], "priority": [2026, 2025, 2024]}},
    }
    candidates = [
        candidate("old", 2024, 0.99),
        candidate("new-1", 2026, 0.90),
        candidate("new-2", 2025, 0.88),
        candidate("new-3", 2025, 0.87),
    ]
    plan = CorpusPlanner(spec).select(candidates)
    assert [item.key for item in plan.auto_accepted] == ["new-1", "new-2", "new-3"]
    assert plan.shortfall == 0


def test_borderline_candidate_is_pending() -> None:
    item = CandidateMetadata(
        "borderline", "Borderline", 2026, "Test", 0.72, True, ("abstract",)
    )
    decision = ScreeningGate().decide(item)
    assert decision.status is PaperStatus.PENDING_REVIEW
    assert "relevance_below_auto_threshold" in decision.reasons


def test_failed_hard_gate_is_rejected_even_with_high_score() -> None:
    decision = ScreeningGate().decide(candidate("wrong-track", 2026, 0.99, hard_gates=False))
    assert decision.status is PaperStatus.REJECTED
    assert "hard_gate_failed" in decision.reasons


def test_group_minimums_are_satisfied_before_global_score_order() -> None:
    spec = {
        "target": {"preferred": 3, "minimum": 2, "maximum": 3},
        "quotas": {
            "groups": [
                {"name": "A", "minimum": 1, "venues": ["Venue A"]},
                {"name": "B", "minimum": 1, "venues": ["Venue B"]},
            ]
        },
    }
    candidates = [
        candidate("a1", 2026, 0.99, venue="Venue A"),
        candidate("a2", 2026, 0.98, venue="Venue A"),
        candidate("b1", 2026, 0.86, venue="Venue B"),
    ]
    selected = CorpusPlanner(spec).select(candidates).auto_accepted
    assert {item.venue for item in selected} == {"Venue A", "Venue B"}


def test_quality_shortfall_never_lowers_threshold() -> None:
    spec = {"target": {"preferred": 3, "minimum": 2, "maximum": 4}}
    plan = CorpusPlanner(spec).select(
        [candidate("one", 2026, 0.90), candidate("borderline", 2026, 0.70)]
    )
    assert [item.key for item in plan.auto_accepted] == ["one"]
    assert [item.key for item in plan.pending_review] == ["borderline"]
    assert plan.shortfall == 1
