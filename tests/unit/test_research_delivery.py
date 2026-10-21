import json
from pathlib import Path

import pytest
from acquire_research_papers.discovery.corpus import CandidateMetadata
from acquire_research_papers.research.delivery import ResearchDelivery
from acquire_research_papers.research.evidence import EvidenceRecord
from acquire_research_papers.research.planner import ResearchPlanner
from acquire_research_papers.research.workflow import GraphBounds


def brief() -> dict:
    return {
        "schema_version": 1,
        "mode": "research",
        "question_type": "gap-analysis",
        "research_question": "Is this coupling already optimized?",
        "work_under_review": {"scenario": "MEC", "mechanism": "LLM-guided EC"},
        "claims": [],
        "seed_papers": [],
        "scope": {"years": [2022, 2023, 2024, 2025, 2026], "venues": []},
        "delivery": {"write_narrative": False, "export_markdown": False},
    }


def test_research_delivery_writes_evidence_package_without_full_text_markdown(tmp_path: Path) -> None:
    candidate = CandidateMetadata(
        "paper-1", "Nearest Work", 2025, "Test", 0.9, True, ("title", "abstract")
    )
    evidence = EvidenceRecord(
        claim_id="gap",
        paper_id="paper-1",
        relation="qualifies",
        read_scope="full-text",
        section="Method",
        page=4,
        excerpt="The method optimizes only one decision variable.",
        explanation="It is close but does not cover the full coupling.",
    ).validate()
    result = ResearchDelivery(tmp_path / "out").write(
        legacy=True,
        brief=brief(),
        plan=ResearchPlanner().build(brief()),
        candidates=[candidate],
        evidence=[evidence],
        graph_bounds=GraphBounds(
            seed_limit=1,
            neighbors_per_direction=10,
            requested_seeds=("10.1000/one", "10.1000/two"),
            expanded_seeds=("10.1000/one",),
            skipped_seeds=("10.1000/two",),
        ),
    )
    assert result.manifest.name == "research-manifest.csv"
    assert result.evidence_map.name == "evidence-map.md"
    assert result.nearest_work_matrix.name == "nearest-work-matrix.csv"
    assert result.gap_analysis.name == "gap-analysis.md"
    assert result.candidates_snapshot.name == "research-candidates.jsonl"
    packet = json.loads(result.candidates_snapshot.read_text(encoding="utf-8"))
    assert packet["candidate"]["key"] == "paper-1"
    assert len(packet["candidate_sha256"]) == 64
    run = json.loads(result.run_manifest.read_text(encoding="utf-8"))
    assert run["candidates_sha256"]
    assert run["status"] == "review_required"
    graph = json.loads(result.citation_graph.read_text(encoding="utf-8"))
    assert graph["bounds"]["skipped_seeds"] == ["10.1000/two"]
    assert "within the searched scope" in result.gap_analysis.read_text(encoding="utf-8")
    assert not list((tmp_path / "out").rglob("paper.md"))
    assert not (tmp_path / "out" / "narrative.md").exists()


def test_research_discovery_cannot_overwrite_an_existing_run(tmp_path: Path) -> None:
    output = tmp_path / "out"
    delivery = ResearchDelivery(output)
    arguments = {
        "brief": brief(),
        "plan": ResearchPlanner().build(brief()),
        "candidates": [],
        "evidence": [],
    }
    delivery.write(**arguments)

    with pytest.raises(ValueError, match="immutable research run"):
        delivery.write(**arguments)


def test_research_delivery_requires_requested_claim_relation(tmp_path: Path) -> None:
    scoped_brief = brief()
    scoped_brief["claims"] = [
        {
            "id": "claim-1",
            "text": "The method directly supports the coupling.",
            "required_relation": "direct-support",
        }
    ]
    candidate = CandidateMetadata(
        "paper-1", "Nearest Work", 2025, "Test", 0.9, True, ("title", "abstract")
    )
    evidence = EvidenceRecord(
        claim_id="claim-1",
        paper_id="paper-1",
        relation="background",
        read_scope="full-text",
        section="Introduction",
        page=1,
        excerpt="Related background.",
        explanation="This is context, not direct support.",
    ).validate()

    result = ResearchDelivery(tmp_path / "out").write(
        legacy=True,
        brief=scoped_brief,
        plan=ResearchPlanner().build(scoped_brief),
        candidates=[candidate],
        evidence=[evidence],
    )

    coverage = result.claim_coverage.read_text(encoding="utf-8-sig")
    assert "required_relation" in coverage
    assert "claim-1" in coverage
    assert "direct-support" in coverage
    assert "unresolved" in coverage


def test_discovery_has_only_resumable_state(tmp_path: Path) -> None:
    result = ResearchDelivery(tmp_path).write(
        brief=brief(), plan=ResearchPlanner().build(brief()), candidates=[], evidence=[]
    )
    assert {p.name for p in tmp_path.iterdir()} == {
        "research-plan.json", "research-run.json", "research-candidates.jsonl", "citation-graph.json"
    }
    assert json.loads(result.run_manifest.read_text())["output_version"] == 2
    assert result.report is None


def test_compact_report_exports_are_optional_and_stale_exports_removed(tmp_path: Path) -> None:
    delivery = ResearchDelivery(tmp_path)
    arguments = dict(brief=brief(), plan=ResearchPlanner().build(brief()), candidates=[],
                     evidence=[], run_status="evidence_required", pending_paper_ids=["pending-paper"])
    exported = delivery.write(**arguments, export_csv=True)
    assert exported.manifest.name == "papers.csv"
    result = delivery.write(**arguments)
    assert {p.name for p in tmp_path.iterdir()} == {"report.md"}
    text = result.report.read_text(encoding="utf-8")
    assert "pending-paper" in text
    assert "unresolved" in text
    assert "No novelty conclusion" in text
    assert "2026" in text
    assert "Closest counterexamples and qualifiers" in text
    assert result.claim_coverage is None


def test_related_work_report_has_no_gap_conclusion(tmp_path: Path) -> None:
    request = {**brief(), "question_type": "related-work"}
    result = ResearchDelivery(tmp_path).write(
        brief=request, plan=ResearchPlanner().build(request), candidates=[], evidence=[], run_status="complete"
    )
    assert "Bounded conclusion" not in result.report.read_text(encoding="utf-8")
