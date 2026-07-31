import json
from pathlib import Path

from acquire_research_papers.acquisition.corpus import CorpusAcquisitionWorkflow
from acquire_research_papers.artifacts import sha256_file
from acquire_research_papers.cli import Application, run_cli
from acquire_research_papers.discovery.contracts import CandidateMetadata
from acquire_research_papers.mineru import MineruCache, MineruResult
from acquire_research_papers.research.fulltext import ResearchFullTextWorkflow
from acquire_research_papers.research.workflow import ResearchWorkflow


def test_research_cli_plans_queries_and_writes_default_evidence_package(
    tmp_path: Path,
    capsys,
) -> None:
    brief = tmp_path / "brief.yaml"
    brief.write_text(
        """schema_version: 1
mode: research
question_type: gap-analysis
research_question: Does prior work optimize this coupling?
work_under_review:
  scenario: MEC
  mechanism: LLM-guided evolutionary computation
seed_papers: []
delivery:
  write_narrative: false
  export_markdown: false
""",
        encoding="utf-8",
    )
    application = Application.for_test(
        app_root=tmp_path / "app",
        repository_root=tmp_path / "repository",
        research_workflow=ResearchWorkflow(discoverer=lambda _: []),
    )
    output = tmp_path / "research-output"
    exit_code = run_cli(
        ["discover", "research", "--brief", str(brief), "--output", str(output)],
        application=application,
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "review_required"
    assert payload["query_passes"] == 4
    for filename in (
        "research-manifest.csv",
        "pending-review.csv",
        "evidence-map.md",
        "nearest-work-matrix.csv",
        "gap-analysis.md",
        "research-plan.json",
        "research-candidates.jsonl",
        "citation-graph.json",
        "research-run.json",
    ):
        assert (output / filename).is_file()
    run = json.loads((output / "research-run.json").read_text(encoding="utf-8"))
    assert run["phase"] == "discovery"
    assert run["status"] == "review_required"
    assert run["candidate_count"] == 0
    assert not (output / "narrative.md").exists()

    repeated = run_cli(
        ["discover", "research", "--brief", str(brief), "--output", str(output)],
        application=application,
    )
    repeated_payload = json.loads(capsys.readouterr().out)
    assert repeated == 64
    assert repeated_payload["error_code"] == "invalid_input"
    assert "immutable research run" in repeated_payload["message"]


def test_research_cli_runs_discovery_review_acquisition_and_evidence_end_to_end(
    tmp_path: Path,
    capsys,
) -> None:
    brief = tmp_path / "brief.yaml"
    brief.write_text(
        """schema_version: 1
mode: research
question_type: gap-analysis
research_question: Does prior work optimize this coupling?
claims:
  - id: claim-1
    text: The method jointly optimizes placement and scheduling.
analysis:
  max_full_text_papers: 5
""",
        encoding="utf-8",
    )
    candidate = CandidateMetadata(
        key="paper-1",
        title="Nearest Work",
        year=2025,
        venue="Test Venue",
        relevance_score=0.95,
        hard_gates_passed=True,
        evidence_fields=("title", "abstract"),
        doi="10.1000/nearest",
        official_url="https://publisher.example/nearest",
        abstract="A close match.",
    )

    def acquirer(record, output: Path):
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

    def mineru(_pdf: Path, output: Path) -> MineruResult:
        result = output / "precision"
        result.mkdir(parents=True, exist_ok=True)
        markdown = result / "paper.md"
        markdown.write_text(
            "# Method\n\nThe method jointly optimizes placement and scheduling.\n",
            encoding="utf-8",
        )
        return MineruResult("precision", result, markdown)

    acquisition = CorpusAcquisitionWorkflow(acquirer=acquirer)
    application = Application.for_test(
        app_root=tmp_path / "app",
        repository_root=tmp_path / "repository",
        research_workflow=ResearchWorkflow(discoverer=lambda _plan: [candidate]),
        corpus_acquisition=acquisition,
        research_fulltext=ResearchFullTextWorkflow(
            acquisition=acquisition,
            mineru_cache=MineruCache(tmp_path / "cache", runner=mineru),
        ),
    )
    output = tmp_path / "research-run"

    assert run_cli(
        ["discover", "research", "--brief", str(brief), "--output", str(output)],
        application=application,
    ) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "review_required"
    packet = json.loads((output / "research-candidates.jsonl").read_text(encoding="utf-8"))
    review = tmp_path / "review.jsonl"
    review.write_text(
        json.dumps(
            {
                "candidate_id": packet["candidate_id"],
                "candidate_sha256": packet["candidate_sha256"],
                "decision": "include",
                "claims": ["claim-1"],
                "reason": "Closest full-mechanism match.",
                "reviewer": "codex",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert run_cli(
        ["review", "research", "--run", str(output), "--decisions", str(review)],
        application=application,
    ) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "acquisition_required"

    assert run_cli(
        ["acquire", "research", "--run", str(output)],
        application=application,
    ) == 0
    acquisition_payload = json.loads(capsys.readouterr().out)
    assert acquisition_payload["status"] == "evidence_required"
    assert acquisition_payload["acquisition_pending"] == 0
    assert acquisition_payload["parsing_pending"] == 0
    fulltext = json.loads((output / "full-text-manifest.jsonl").read_text(encoding="utf-8"))
    evidence = tmp_path / "evidence.jsonl"
    evidence.write_text(
        json.dumps(
            {
                "selection_id": fulltext["selection_id"],
                "full_text_sha256": fulltext["pdf_sha256"],
                "markdown_sha256": fulltext["markdown_sha256"],
                "review_status": "reviewed",
                "summary": "The method section was checked in full.",
                "reviewer": "codex",
                "records": [
                    {
                        "claim_id": "claim-1",
                        "paper_id": fulltext["selection_id"],
                        "relation": "direct-support",
                        "read_scope": "full-text",
                        "section": "Method",
                        "page": 3,
                        "excerpt": "The method jointly optimizes placement and scheduling.",
                        "explanation": "The paper explicitly optimizes both decisions.",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert run_cli(
        ["evidence", "research", "--run", str(output), "--records", str(evidence)],
        application=application,
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "complete"
    assert Path(payload["evidence_map"]).is_file()
    assert Path(payload["claim_coverage"]).is_file()
