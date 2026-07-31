import json
from pathlib import Path

import pytest

from acquire_research_papers.artifacts import sha256_file
from acquire_research_papers.discovery.corpus import CandidateMetadata
from acquire_research_papers.research.delivery import ResearchDelivery
from acquire_research_papers.research.planner import ResearchPlanner
from acquire_research_papers.research.review import ResearchReviewWorkflow
from acquire_research_papers.selection import SelectionStore


def _brief() -> dict:
    return {
        "schema_version": 1,
        "mode": "research",
        "question_type": "gap-analysis",
        "research_question": "Has prior work solved the coupling?",
        "claims": [{"id": "claim-1", "text": "The coupling is not jointly optimized."}],
        "analysis": {"max_full_text_papers": 5},
    }


def _run(tmp_path: Path) -> tuple[Path, list[dict]]:
    candidate = CandidateMetadata(
        key="paper-1",
        title="Nearest Work",
        year=2025,
        venue="Test",
        relevance_score=0.9,
        hard_gates_passed=True,
        evidence_fields=("title", "abstract"),
        doi="10.1000/nearest",
        official_url="https://doi.org/10.1000/nearest",
        abstract="A close paper.",
    )
    root = tmp_path / "run"
    ResearchDelivery(root).write(
        brief=_brief(),
        plan=ResearchPlanner().build(_brief()),
        candidates=[candidate],
        evidence=[],
    )
    packets = [
        json.loads(line)
        for line in (root / "research-candidates.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    return root, packets


def _run_two(tmp_path: Path) -> tuple[Path, list[dict]]:
    candidates = [
        CandidateMetadata(
            key=f"paper-{index}",
            title=f"Nearest Work {index}",
            year=2025,
            venue="Test",
            relevance_score=0.9 - index / 100,
            hard_gates_passed=True,
            evidence_fields=("title", "abstract"),
            doi=f"10.1000/nearest-{index}",
            official_url=f"https://doi.org/10.1000/nearest-{index}",
            abstract="A close paper.",
        )
        for index in (1, 2)
    ]
    root = tmp_path / "run"
    ResearchDelivery(root).write(
        brief=_brief(),
        plan=ResearchPlanner().build(_brief()),
        candidates=candidates,
        evidence=[],
    )
    packets = [
        json.loads(line)
        for line in (root / "research-candidates.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    return root, packets


def _decision(packet: dict, verdict: str) -> dict:
    return {
        "candidate_id": packet["candidate_id"],
        "candidate_sha256": packet["candidate_sha256"],
        "decision": verdict,
        "claims": ["claim-1"],
        "reason": "Explicit closest-paper review decision.",
        "reviewer": "codex",
    }


def test_research_review_freezes_hash_bound_closest_papers(tmp_path: Path) -> None:
    root, packets = _run(tmp_path)
    decisions = tmp_path / "decisions.jsonl"
    decisions.write_text(
        json.dumps(
            {
                "candidate_id": packets[0]["candidate_id"],
                "candidate_sha256": packets[0]["candidate_sha256"],
                "decision": "include",
                "claims": ["claim-1"],
                "reason": "This is the closest mechanism-level match.",
                "reviewer": "codex",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = ResearchReviewWorkflow().run(root, decisions)

    assert result.status == "acquisition_required"
    selection = SelectionStore.load(result.selection_manifest_path)
    assert selection.records[0].doi == "10.1000/nearest"
    assert selection.manifest["phase"] == "research-review"
    assert selection.manifest["reviewed_file"] == "reviewed-research.jsonl"
    assert len(selection.manifest["reviewed_sha256"]) == 64
    assert selection.manifest["review_manifest_file"] == "research-review.json"
    assert selection.manifest["review_manifest_sha256"] == sha256_file(
        result.manifest_path
    )
    review = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert review["candidate_snapshot_sha256"] == json.loads(
        (root / "research-run.json").read_text(encoding="utf-8")
    )["candidates_sha256"]
    assert review["reviewed_sha256"] == selection.manifest["reviewed_sha256"]


def test_research_review_rejects_stale_candidate_hash(tmp_path: Path) -> None:
    root, packets = _run(tmp_path)
    decisions = tmp_path / "decisions.jsonl"
    decisions.write_text(
        json.dumps(
            {
                "candidate_id": packets[0]["candidate_id"],
                "candidate_sha256": "0" * 64,
                "decision": "include",
                "claims": ["claim-1"],
                "reason": "Looks relevant.",
                "reviewer": "codex",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="candidate SHA-256"):
        ResearchReviewWorkflow().run(root, decisions)


def test_research_review_requires_explicit_codex_decision_for_every_candidate(
    tmp_path: Path,
) -> None:
    root, _ = _run(tmp_path)
    decisions = tmp_path / "decisions.jsonl"
    decisions.write_text("", encoding="utf-8")

    result = ResearchReviewWorkflow().run(root, decisions)

    assert result.status == "review_required"
    assert result.pending == 1
    assert result.selection_manifest_path is None


def test_research_review_cannot_include_candidate_without_title_and_abstract_evidence(
    tmp_path: Path,
) -> None:
    brief = _brief()
    candidate = CandidateMetadata(
        key="paper-1",
        title="Metadata-only lead",
        year=2025,
        venue="Test",
        relevance_score=0.9,
        hard_gates_passed=True,
        evidence_fields=("title",),
        doi="10.1000/metadata-only",
        abstract="",
    )
    root = tmp_path / "run"
    delivery = ResearchDelivery(root).write(
        brief=brief,
        plan=ResearchPlanner().build(brief),
        candidates=[candidate],
        evidence=[],
    )
    packet = json.loads(delivery.candidates_snapshot.read_text(encoding="utf-8"))
    decisions = tmp_path / "decisions.jsonl"
    decisions.write_text(
        json.dumps(
            {
                "candidate_id": packet["candidate_id"],
                "candidate_sha256": packet["candidate_sha256"],
                "decision": "include",
                "claims": ["claim-1"],
                "reason": "Title looks close.",
                "reviewer": "codex",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="title and abstract"):
        ResearchReviewWorkflow().run(root, decisions)


def test_research_review_resume_merges_prior_partial_decisions(tmp_path: Path) -> None:
    root, packets = _run_two(tmp_path)
    decisions = tmp_path / "decisions.jsonl"
    decisions.write_text(json.dumps(_decision(packets[0], "include")) + "\n", encoding="utf-8")
    first = ResearchReviewWorkflow().run(root, decisions)
    decisions.write_text(json.dumps(_decision(packets[1], "exclude")) + "\n", encoding="utf-8")

    resumed = ResearchReviewWorkflow().run(root, decisions)

    assert first.status == "review_required"
    assert resumed.status == "acquisition_required"
    assert resumed.included == 1
    assert resumed.excluded == 1
    assert resumed.pending == 0


def test_research_review_rejects_mutation_of_frozen_selection(tmp_path: Path) -> None:
    root, packets = _run_two(tmp_path)
    decisions = tmp_path / "decisions.jsonl"
    decisions.write_text(
        "\n".join(
            json.dumps(row)
            for row in (
                _decision(packets[0], "include"),
                _decision(packets[1], "exclude"),
            )
        )
        + "\n",
        encoding="utf-8",
    )
    ResearchReviewWorkflow().run(root, decisions)
    decisions.write_text(
        "\n".join(
            json.dumps(row)
            for row in (
                _decision(packets[0], "exclude"),
                _decision(packets[1], "include"),
            )
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="frozen research review differs"):
        ResearchReviewWorkflow().run(root, decisions)


def test_research_review_rejects_changed_reason_after_selection_freezes(
    tmp_path: Path,
) -> None:
    root, packets = _run(tmp_path)
    decisions = tmp_path / "decisions.jsonl"
    original = _decision(packets[0], "include")
    decisions.write_text(json.dumps(original) + "\n", encoding="utf-8")
    ResearchReviewWorkflow().run(root, decisions)
    changed = {**original, "reason": "A different audit explanation."}
    decisions.write_text(json.dumps(changed) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="frozen research review differs"):
        ResearchReviewWorkflow().run(root, decisions)
