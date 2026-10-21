import json
from pathlib import Path

import pytest

from acquire_research_papers.acquisition.corpus import CorpusAcquisitionWorkflow
from acquire_research_papers.mineru import MineruCache
from acquire_research_papers.research.evidence_workflow import ResearchEvidenceWorkflow
from acquire_research_papers.research.fulltext import ResearchFullTextWorkflow
from test_research_fulltext import (
    FakeMineru,
    delivered_outcome,
    prepare_reviewed_run,
)


def _parsed_run(tmp_path: Path):
    root = prepare_reviewed_run(tmp_path)
    fulltext = ResearchFullTextWorkflow(
        acquisition=CorpusAcquisitionWorkflow(acquirer=delivered_outcome),
        mineru_cache=MineruCache(tmp_path / "cache", runner=FakeMineru()),
    ).run(root)
    row = json.loads(fulltext.full_text_manifest.read_text(encoding="utf-8"))
    return root, row


def _write_evidence(path: Path, row: dict, excerpt: str) -> None:
    path.write_text(
        json.dumps(
            {
                "selection_id": row["selection_id"],
                "full_text_sha256": row["pdf_sha256"],
                "markdown_sha256": row["markdown_sha256"],
                "review_status": "reviewed",
                "summary": "The full method section was checked.",
                "reviewer": "codex",
                "records": [
                    {
                        "claim_id": "claim-1",
                        "paper_id": row["selection_id"],
                        "relation": "direct-support",
                        "read_scope": "full-text",
                        "section": "Method",
                        "page": 3,
                        "excerpt": excerpt,
                        "explanation": "The method explicitly covers both decisions.",
                        "strength": "strong",
                        "uncertainty": "",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize("host", ["codex", "claude-code", "kiro-ide", "kiro-cli", "other-agent"])
def test_research_evidence_v2_retains_actual_executor(tmp_path: Path, host: str) -> None:
    root, row = _parsed_run(tmp_path)
    decisions = tmp_path / "evidence.jsonl"
    _write_evidence(decisions, row, "The method jointly optimizes placement and scheduling.")
    executor = {"host": host, "model": "review-model", "version": "1.0"}
    record = {
        **json.loads(decisions.read_text(encoding="utf-8")),
        "schema_version": 2,
        "reviewer": host,
        "executor": executor,
    }
    decisions.write_text(json.dumps(record) + "\n", encoding="utf-8")

    result = ResearchEvidenceWorkflow().run(root, decisions)

    assert result.status == "complete"
    assert json.loads(result.reviewed_path.read_text(encoding="utf-8")) == record
    decisions.write_text("", encoding="utf-8")
    assert ResearchEvidenceWorkflow().run(root, decisions).reviewed == 1


@pytest.mark.parametrize(
    "metadata",
    [
        {"reviewer": "kiro-cli"},
        {"executor": {"host": "codex"}},
        {"schema_version": 2},
        {"schema_version": 2, "executor": {"host": "kiro-ide"}},
        {"schema_version": 2, "executor": {"host": "codex", "version": " "}},
    ],
)
def test_research_evidence_rejects_invalid_executor_metadata(
    tmp_path: Path,
    metadata: dict,
) -> None:
    root, row = _parsed_run(tmp_path)
    decisions = tmp_path / "evidence.jsonl"
    _write_evidence(decisions, row, "The method jointly optimizes placement and scheduling.")
    record = {**json.loads(decisions.read_text(encoding="utf-8")), **metadata}
    decisions.write_text(json.dumps(record) + "\n", encoding="utf-8")

    with pytest.raises(ValueError):
        ResearchEvidenceWorkflow().run(root, decisions)


def test_research_evidence_v2_still_rejects_stale_fulltext(tmp_path: Path) -> None:
    root, row = _parsed_run(tmp_path)
    decisions = tmp_path / "evidence.jsonl"
    _write_evidence(decisions, row, "The method jointly optimizes placement and scheduling.")
    record = {
        **json.loads(decisions.read_text(encoding="utf-8")),
        "schema_version": 2,
        "reviewer": "claude-code",
        "executor": {"host": "claude-code"},
        "markdown_sha256": "0" * 64,
    }
    decisions.write_text(json.dumps(record) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Markdown SHA-256"):
        ResearchEvidenceWorkflow().run(root, decisions)


def test_legacy_research_evidence_preserves_audit_bytes(tmp_path: Path) -> None:
    root, row = _parsed_run(tmp_path)
    decisions = tmp_path / "evidence.jsonl"
    _write_evidence(decisions, row, "The method jointly optimizes placement and scheduling.")
    record = json.loads(decisions.read_text(encoding="utf-8"))
    expected = json.dumps(record, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n"

    result = ResearchEvidenceWorkflow().run(root, decisions)

    assert result.reviewed_path.read_bytes() == expected


def test_research_evidence_import_verifies_excerpt_and_fills_reports(tmp_path: Path) -> None:
    root, row = _parsed_run(tmp_path)
    decisions = tmp_path / "evidence.jsonl"
    excerpt = "The method jointly optimizes placement and scheduling."
    _write_evidence(decisions, row, excerpt)

    result = ResearchEvidenceWorkflow().run(root, decisions)

    assert result.status == "complete"
    assert result.reviewed == 1
    assert result.pending == 0
    assert excerpt in result.report.read_text(encoding="utf-8")
    assert {p.name for p in (root / "reports").iterdir()} == {"report.md"}
    assert result.pending_path is None
    result = ResearchEvidenceWorkflow().run(root, decisions, export_csv=True)
    coverage = result.claim_coverage.read_text(encoding="utf-8-sig")
    assert "claim-1" in coverage
    assert "direct-support" in coverage
    manifest = result.papers
    assert "reviewed" in manifest.read_text(encoding="utf-8-sig")
    assert not (root / "reports" / "pending-review.csv").exists()
    run = json.loads((root / "research-run.json").read_text(encoding="utf-8"))
    assert run["status"] == "complete"


def test_old_run_keeps_legacy_reports_on_resume(tmp_path: Path) -> None:
    root, row = _parsed_run(tmp_path)
    run_path = root / "research-run.json"
    run = json.loads(run_path.read_text(encoding="utf-8"))
    run.pop("output_version")
    run_path.write_text(json.dumps(run), encoding="utf-8")
    decisions = tmp_path / "evidence.jsonl"
    _write_evidence(decisions, row, "The method jointly optimizes placement and scheduling.")
    result = ResearchEvidenceWorkflow().run(root, decisions)
    assert result.evidence_map.is_file()
    assert result.claim_coverage.is_file()
    assert result.report is None
    assert result.pending_path.is_file()


def test_partial_evidence_report_discloses_pending_papers(tmp_path: Path) -> None:
    root, row = _parsed_run(tmp_path)
    decisions = tmp_path / "empty.jsonl"
    decisions.write_text("", encoding="utf-8")
    result = ResearchEvidenceWorkflow().run(root, decisions)
    assert result.status == "evidence_required"
    assert row["selection_id"] in result.report.read_text(encoding="utf-8")
    assert result.pending_path.is_file()


def test_research_evidence_resume_reuses_prior_validated_decisions(tmp_path: Path) -> None:
    root, row = _parsed_run(tmp_path)
    decisions = tmp_path / "evidence.jsonl"
    _write_evidence(
        decisions,
        row,
        "The method jointly optimizes placement and scheduling.",
    )
    first = ResearchEvidenceWorkflow().run(root, decisions)
    decisions.write_text("", encoding="utf-8")

    resumed = ResearchEvidenceWorkflow().run(root, decisions)

    assert first.status == resumed.status == "complete"
    assert resumed.reviewed == 1
    assert resumed.evidence_records == 1


def test_research_evidence_rejects_excerpt_absent_from_bound_markdown(tmp_path: Path) -> None:
    root, row = _parsed_run(tmp_path)
    decisions = tmp_path / "evidence.jsonl"
    _write_evidence(decisions, row, "This sentence does not occur in the paper.")

    with pytest.raises(ValueError, match="excerpt was not found"):
        ResearchEvidenceWorkflow().run(root, decisions)


def test_research_evidence_rejects_non_full_text_records(tmp_path: Path) -> None:
    root, row = _parsed_run(tmp_path)
    decisions = tmp_path / "evidence.jsonl"
    _write_evidence(
        decisions,
        row,
        "The method jointly optimizes placement and scheduling.",
    )
    payload = json.loads(decisions.read_text(encoding="utf-8"))
    payload["records"][0]["relation"] = "background"
    payload["records"][0]["read_scope"] = "abstract-only"
    decisions.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="full-text"):
        ResearchEvidenceWorkflow().run(root, decisions)


def test_research_evidence_rejects_stale_full_text_hash(tmp_path: Path) -> None:
    root, row = _parsed_run(tmp_path)
    decisions = tmp_path / "evidence.jsonl"
    stale = dict(row)
    stale["pdf_sha256"] = "0" * 64
    _write_evidence(decisions, stale, "The method jointly optimizes placement and scheduling.")

    with pytest.raises(ValueError, match="full-text SHA-256"):
        ResearchEvidenceWorkflow().run(root, decisions)


def test_research_evidence_rejects_changed_review_audit(tmp_path: Path) -> None:
    root, row = _parsed_run(tmp_path)
    reviewed = root / "reviewed-research.jsonl"
    reviewed.write_text(reviewed.read_text(encoding="utf-8") + " ", encoding="utf-8")
    decisions = tmp_path / "evidence.jsonl"
    _write_evidence(
        decisions,
        row,
        "The method jointly optimizes placement and scheduling.",
    )

    with pytest.raises(ValueError, match="review audit SHA-256"):
        ResearchEvidenceWorkflow().run(root, decisions)


def test_research_evidence_rejects_review_for_pending_full_text(tmp_path: Path) -> None:
    root = prepare_reviewed_run(tmp_path)
    fulltext = ResearchFullTextWorkflow(
        acquisition=CorpusAcquisitionWorkflow(
            acquirer=lambda _record, _output: {"error_code": "access_required"}
        ),
        mineru_cache=MineruCache(tmp_path / "cache", runner=FakeMineru()),
    ).run(root)
    row = json.loads(fulltext.full_text_manifest.read_text(encoding="utf-8"))
    decisions = tmp_path / "evidence.jsonl"
    decisions.write_text(
        json.dumps(
            {
                "selection_id": row["selection_id"],
                "full_text_sha256": "0" * 64,
                "markdown_sha256": "0" * 64,
                "review_status": "insufficient-text",
                "summary": "No full text was available.",
                "reviewer": "codex",
                "records": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="pending full text"):
        ResearchEvidenceWorkflow().run(root, decisions)
