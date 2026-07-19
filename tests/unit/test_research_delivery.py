from pathlib import Path

from acquire_research_papers.discovery.corpus import CandidateMetadata
from acquire_research_papers.research.delivery import ResearchDelivery
from acquire_research_papers.research.evidence import EvidenceRecord
from acquire_research_papers.research.planner import ResearchPlanner


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
        brief=brief(),
        plan=ResearchPlanner().build(brief()),
        candidates=[candidate],
        evidence=[evidence],
    )
    assert result.manifest.name == "research-manifest.csv"
    assert result.evidence_map.name == "evidence-map.md"
    assert result.nearest_work_matrix.name == "nearest-work-matrix.csv"
    assert result.gap_analysis.name == "gap-analysis.md"
    assert "within the searched scope" in result.gap_analysis.read_text(encoding="utf-8")
    assert not list((tmp_path / "out").rglob("paper.md"))
    assert not (tmp_path / "out" / "narrative.md").exists()
