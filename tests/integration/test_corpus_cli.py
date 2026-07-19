import json
from pathlib import Path

from acquire_research_papers.cli import Application, run_cli
from acquire_research_papers.discovery.corpus import CandidateMetadata, CorpusWorkflow


def test_corpus_cli_writes_candidates_and_pending_review(tmp_path: Path, capsys) -> None:
    spec = tmp_path / "job.yaml"
    spec.write_text(
        "mode: corpus\nname: test\ntarget:\n  minimum: 1\n  preferred: 1\n  maximum: 2\n",
        encoding="utf-8",
    )
    candidates = [
        CandidateMetadata("high", "High", 2026, "Test", 0.91, True, ("title", "abstract")),
        CandidateMetadata("edge", "Edge", 2026, "Test", 0.72, True, ("abstract",)),
    ]
    workflow = CorpusWorkflow(discoverer=lambda _: candidates)
    application = Application.for_test(
        app_root=tmp_path / "app",
        repository_root=tmp_path / "repository",
        corpus_workflow=workflow,
    )
    output = tmp_path / "output"
    exit_code = run_cli(
        ["discover", "corpus", "--spec", str(spec), "--output", str(output)],
        application=application,
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "planned"
    assert (output / "candidates.jsonl").is_file()
    assert (output / "pending-review.csv").is_file()
    assert "bibtex" not in (output / "candidates.jsonl").read_text(encoding="utf-8").casefold()


def test_corpus_cli_auto_acquires_only_high_confidence_candidates(
    tmp_path: Path,
    capsys,
) -> None:
    spec = tmp_path / "job.yaml"
    spec.write_text(
        "mode: corpus\nname: acquire\ntarget:\n  minimum: 1\n  preferred: 1\n  maximum: 2\n",
        encoding="utf-8",
    )
    candidates = [
        CandidateMetadata(
            "high",
            "High",
            2026,
            "Test",
            0.91,
            True,
            ("title", "abstract"),
            doi="10.1000/high",
        ),
        CandidateMetadata(
            "edge",
            "Edge",
            2026,
            "Test",
            0.72,
            True,
            ("abstract",),
            doi="10.1000/edge",
        ),
    ]
    acquired = []

    def acquirer(candidate, output):
        acquired.append(candidate.key)
        bundle = output / candidate.key
        bundle.mkdir(parents=True)
        paths = {
            "pdf": bundle / "paper.pdf",
            "bibtex": bundle / "citation.bib",
            "provenance": bundle / "provenance.json",
        }
        paths["pdf"].write_bytes(b"%PDF-1.7\n%%EOF\n")
        paths["bibtex"].write_text("@article{k}\n", encoding="utf-8")
        paths["provenance"].write_text("{}\n", encoding="utf-8")
        return {"status": "delivered", **{key: str(value) for key, value in paths.items()}}

    workflow = CorpusWorkflow(discoverer=lambda _: candidates, acquirer=acquirer)
    application = Application.for_test(
        app_root=tmp_path / "app",
        repository_root=tmp_path / "repository",
        corpus_workflow=workflow,
    )
    output = tmp_path / "output"
    exit_code = run_cli(
        ["discover", "corpus", "--spec", str(spec), "--output", str(output)],
        application=application,
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert acquired == ["high"]
    assert payload["status"] == "delivered"
    assert payload["delivered"] == 1
    assert payload["deferred"] == 0
    rows = [json.loads(line) for line in (output / "acquisition-manifest.jsonl").read_text().splitlines()]
    assert rows[0]["key"] == "high"
    assert rows[0]["status"] == "delivered"
