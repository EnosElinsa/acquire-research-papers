from dataclasses import replace

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


def test_group_maximum_is_never_exceeded() -> None:
    spec = {
        "target": {"minimum": 2, "preferred": 3, "maximum": 3},
        "quotas": {
            "groups": [
                {
                    "name": "conference",
                    "minimum": 1,
                    "maximum": 1,
                    "venues": ["Conf"],
                }
            ]
        },
    }
    plan = CorpusPlanner(spec).select(
        [
            candidate("c1", 2026, 0.99, venue="Conf"),
            candidate("c2", 2026, 0.98, venue="Conf"),
            candidate("j1", 2026, 0.90, venue="Journal"),
        ]
    )

    assert [item.key for item in plan.auto_accepted] == ["c1", "j1"]
    assert plan.quota_shortfalls == ()


def test_recent_window_ratio_uses_publication_date() -> None:
    spec = {
        "target": {"minimum": 2, "preferred": 2, "maximum": 3},
        "quotas": {
            "recent_window": {"from": "2025-07-18", "minimum_ratio": 0.5}
        },
    }
    old = replace(candidate("old", 2026, 0.99), publication_date="2025-01-01")
    recent = replace(candidate("recent", 2025, 0.86), publication_date="2025-08-01")

    plan = CorpusPlanner(spec).select([old, recent])

    assert {item.key for item in plan.auto_accepted} == {"old", "recent"}
    assert plan.quota_shortfalls == ()


def test_named_quota_shortfall_does_not_lower_screening_threshold() -> None:
    spec = {
        "target": {"minimum": 2, "preferred": 2, "maximum": 2},
        "quotas": {
            "groups": [
                {"name": "journals", "minimum": 2, "venues": ["Journal"]}
            ]
        },
    }

    plan = CorpusPlanner(spec).select(
        [
            candidate("journal", 2026, 0.90, venue="Journal"),
            candidate("border", 2026, 0.70, venue="Journal"),
        ]
    )

    assert [item.key for item in plan.auto_accepted] == ["journal"]
    assert [item.key for item in plan.pending_review] == ["border"]
    assert plan.quota_shortfalls == ("group:journals:1", "global:1")


def test_recent_window_shortfall_is_named() -> None:
    spec = {
        "target": {"minimum": 2, "preferred": 2, "maximum": 2},
        "quotas": {
            "recent_window": {"from": "2025-07-18", "minimum_ratio": 0.5}
        },
    }
    candidates = [
        replace(candidate("old-1", 2026, 0.99), publication_date="2025-01-01"),
        replace(candidate("old-2", 2026, 0.98), publication_date="2025-02-01"),
    ]

    plan = CorpusPlanner(spec).select(candidates)

    assert plan.quota_shortfalls == ("recent:1",)


def test_topic_exclusion_uses_word_boundaries() -> None:
    from acquire_research_papers.discovery.corpus import CorpusDiscoverer

    spec = {
        "target": {"minimum": 1, "preferred": 1, "maximum": 2},
        "scope": {
            "topics": {
                "include": ["multi-agent"],
                "exclude": ["demo"],
            }
        },
    }
    research = replace(
        candidate("research", 2026, 0.0),
        title="Multi-Agent Research",
        abstract="Experiments demonstrate the method.",
    )
    demo = replace(
        candidate("demo", 2026, 0.0),
        title="Multi-Agent Demo System",
        abstract="A conference demo paper.",
    )

    assert CorpusDiscoverer._screen(research, spec).hard_gates_passed
    assert not CorpusDiscoverer._screen(demo, spec).hard_gates_passed


def test_missing_lexical_signal_does_not_fail_hard_gates() -> None:
    from acquire_research_papers.discovery.corpus import CorpusDiscoverer

    spec = {
        "target": {"minimum": 1, "preferred": 1, "maximum": 2},
        "scope": {
            "venues": [{"name": "Test"}],
            "years": {"include": [2026]},
            "publication_types": {"include": ["journal-article"]},
            "topics": {"include": ["evolutionary optimization"]},
        },
    }
    unrelated = replace(
        candidate("semantic-review-needed", 2026, 0.99),
        title="Learning Transferable Representations",
        abstract="The method transfers knowledge between related tasks.",
        publication_type="journal-article",
    )

    screened = CorpusDiscoverer._screen(unrelated, spec)

    assert screened.hard_gates_passed
    assert screened.relevance_score < ScreeningGate().auto_threshold
