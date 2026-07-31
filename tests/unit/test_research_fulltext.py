import json
from pathlib import Path

import pytest

from acquire_research_papers.acquisition.corpus import CorpusAcquisitionWorkflow
from acquire_research_papers.artifacts import sha256_file
from acquire_research_papers.discovery.contracts import CandidateMetadata
from acquire_research_papers.mineru import (
    MineruCache,
    MineruExtractionError,
    MineruResult,
)
from acquire_research_papers.research.delivery import ResearchDelivery
from acquire_research_papers.research.fulltext import ResearchFullTextWorkflow
from acquire_research_papers.research.planner import ResearchPlanner
from acquire_research_papers.research.review import ResearchReviewWorkflow


class FakeMineru:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, _pdf: Path, output: Path) -> MineruResult:
        self.calls += 1
        result = output / "precision"
        result.mkdir(parents=True, exist_ok=True)
        markdown = result / "paper.md"
        markdown.write_text(
            "# Method\n\nThe method jointly optimizes placement and scheduling.\n",
            encoding="utf-8",
        )
        return MineruResult("precision", result, markdown)


def prepare_reviewed_run(tmp_path: Path) -> Path:
    brief = {
        "schema_version": 1,
        "mode": "research",
        "question_type": "gap-analysis",
        "research_question": "Is the coupling jointly optimized?",
        "claims": [{"id": "claim-1", "text": "The coupling is jointly optimized."}],
        "analysis": {"max_full_text_papers": 5},
    }
    candidate = CandidateMetadata(
        key="paper-1",
        title="Nearest Work",
        year=2025,
        venue="Test Venue",
        relevance_score=0.9,
        hard_gates_passed=True,
        evidence_fields=("title", "abstract"),
        doi="10.1000/nearest",
        official_url="https://publisher.example/nearest",
        abstract="A close paper.",
    )
    root = tmp_path / "run"
    delivery = ResearchDelivery(root).write(
        brief=brief,
        plan=ResearchPlanner().build(brief),
        candidates=[candidate],
        evidence=[],
    )
    packet = json.loads(delivery.candidates_snapshot.read_text(encoding="utf-8"))
    decisions = tmp_path / "review.jsonl"
    decisions.write_text(
        json.dumps(
            {
                "candidate_id": packet["candidate_id"],
                "candidate_sha256": packet["candidate_sha256"],
                "decision": "include",
                "claims": ["claim-1"],
                "reason": "Closest mechanism-level match.",
                "reviewer": "codex",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    ResearchReviewWorkflow().run(root, decisions)
    return root


def delivered_outcome(record, output: Path) -> dict[str, str]:
    paths = {
        "pdf": (output / record.relative_pdf).resolve(),
        "bibtex": (output / record.relative_bibtex).resolve(),
        "provenance": (output / record.relative_provenance).resolve(),
    }
    paths["pdf"].parent.mkdir(parents=True, exist_ok=True)
    paths["pdf"].write_bytes(b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n")
    paths["bibtex"].write_text("@article{k}\n", encoding="utf-8")
    paths["provenance"].write_text("{}\n", encoding="utf-8")
    return {
        "status": "delivered",
        **{name: str(path) for name, path in paths.items()},
        **{f"{name}_sha256": sha256_file(path) for name, path in paths.items()},
    }


def test_research_fulltext_acquires_and_parses_frozen_selection_resumably(
    tmp_path: Path,
) -> None:
    root = prepare_reviewed_run(tmp_path)
    mineru = FakeMineru()
    workflow = ResearchFullTextWorkflow(
        acquisition=CorpusAcquisitionWorkflow(acquirer=delivered_outcome),
        mineru_cache=MineruCache(tmp_path / "cache", runner=mineru),
    )

    first = workflow.run(root)
    second = workflow.run(root)

    assert first.status == "evidence_required"
    assert first.parsed == 1
    assert first.pending == 0
    assert first.acquisition_pending == 0
    assert first.parsing_pending == 0
    assert second.parsed == 1
    assert mineru.calls == 1
    row = json.loads(first.full_text_manifest.read_text(encoding="utf-8"))
    assert row["state"] == "parsed"
    assert row["pdf_sha256"]
    assert row["markdown_sha256"]
    assert Path(row["markdown"]).is_file()
    run = json.loads((root / "research-run.json").read_text(encoding="utf-8"))
    assert run["phase"] == "full-text"
    assert run["full_text_sha256"] == sha256_file(first.full_text_manifest)


def test_research_fulltext_rejects_changed_review_audit(tmp_path: Path) -> None:
    root = prepare_reviewed_run(tmp_path)
    reviewed = root / "reviewed-research.jsonl"
    reviewed.write_text(reviewed.read_text(encoding="utf-8") + " ", encoding="utf-8")
    workflow = ResearchFullTextWorkflow(
        acquisition=CorpusAcquisitionWorkflow(acquirer=delivered_outcome),
        mineru_cache=MineruCache(tmp_path / "cache", runner=FakeMineru()),
    )

    with pytest.raises(ValueError, match="review audit SHA-256"):
        workflow.run(root)


def test_research_fulltext_rejects_changed_review_manifest(tmp_path: Path) -> None:
    root = prepare_reviewed_run(tmp_path)
    manifest = root / "research-review.json"
    manifest.write_text(manifest.read_text(encoding="utf-8") + " ", encoding="utf-8")
    workflow = ResearchFullTextWorkflow(
        acquisition=CorpusAcquisitionWorkflow(acquirer=delivered_outcome),
        mineru_cache=MineruCache(tmp_path / "cache", runner=FakeMineru()),
    )

    with pytest.raises(ValueError, match="review manifest SHA-256"):
        workflow.run(root)


def test_research_fulltext_preserves_manual_download_as_pending(tmp_path: Path) -> None:
    root = prepare_reviewed_run(tmp_path)
    workflow = ResearchFullTextWorkflow(
        acquisition=CorpusAcquisitionWorkflow(
            acquirer=lambda _record, _output: {
                "error_code": "access_required",
                "message": "institutional access is required",
            }
        ),
        mineru_cache=MineruCache(tmp_path / "cache", runner=FakeMineru()),
    )

    result = workflow.run(root)

    assert result.status == "acquisition_required"
    assert result.parsed == 0
    assert result.pending == 1
    assert result.acquisition_pending == 1
    assert result.parsing_pending == 0
    row = json.loads(result.full_text_manifest.read_text(encoding="utf-8"))
    assert row["state"] == "pending"
    assert row["reason"] == "access_required"


def test_research_fulltext_distinguishes_parser_failure_from_acquisition(
    tmp_path: Path,
) -> None:
    root = prepare_reviewed_run(tmp_path)

    def parsing_fails(_pdf: Path, _output: Path) -> MineruResult:
        raise MineruExtractionError("parser unavailable")

    result = ResearchFullTextWorkflow(
        acquisition=CorpusAcquisitionWorkflow(acquirer=delivered_outcome),
        mineru_cache=MineruCache(tmp_path / "cache", runner=parsing_fails),
    ).run(root)

    assert result.status == "parsing_required"
    assert result.acquisition_pending == 0
    assert result.parsing_pending == 1
    row = json.loads(result.full_text_manifest.read_text(encoding="utf-8"))
    assert row["state"] == "pending"
    assert row["reason"] == "MineruExtractionError"
