from __future__ import annotations

import json
from pathlib import Path

from acquire_research_papers.cli import Application, run_cli
from acquire_research_papers.discovery.contracts import (
    CandidateMetadata,
    DiscoveryBatch,
    DiscoveryDiagnostic,
)
from acquire_research_papers.discovery.corpus import CorpusDiscoveryWorkflow
from acquire_research_papers.selection import SelectionStore


def test_discover_corpus_writes_frozen_list_without_acquiring(
    tmp_path: Path,
    capsys,
) -> None:
    spec = tmp_path / "job.yaml"
    spec.write_text(
        "mode: corpus\nname: split\ntarget:\n  minimum: 1\n"
        "  preferred: 1\n  maximum: 2\n",
        encoding="utf-8",
    )
    candidate = CandidateMetadata(
        "high",
        "High",
        2026,
        "Test",
        0.91,
        True,
        ("title", "abstract"),
        doi="10.1000/high",
        abstract="Relevant abstract",
    )
    workflow = CorpusDiscoveryWorkflow(
        discoverer=lambda request: DiscoveryBatch(
            (candidate,), covered_slices=(f"fake:{request.name}",)
        ),
    )
    application = Application.for_test(
        app_root=tmp_path / "app",
        repository_root=tmp_path / "repository",
        corpus_discovery=workflow,
    )
    output = tmp_path / "output"

    exit_code = run_cli(
        ["discover", "corpus", "--spec", str(spec), "--output", str(output)],
        application=application,
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "planned"
    assert Path(payload["selected"]).is_file()
    assert Path(payload["selection_manifest"]).is_file()
    selection = SelectionStore.load(Path(payload["selection_manifest"]))
    assert [record.key for record in selection.records] == ["high"]
    assert selection.manifest["provider_coverage"] == ["fake:split"]
    assert not (output / "acquisition-manifest.jsonl").exists()
    assert not (output / "manual-download.csv").exists()
    assert not list(output.rglob("*.pdf"))
    assert not list(output.rglob("*.bib"))
    assert "delivered" not in payload
    assert "deferred" not in payload


def test_discover_corpus_persists_sanitized_provider_diagnostics(
    tmp_path: Path,
    capsys,
) -> None:
    spec = tmp_path / "job.yaml"
    spec.write_text(
        "mode: corpus\nname: diagnostics\ntarget:\n  minimum: 1\n  maximum: 1\n",
        encoding="utf-8",
    )
    diagnostic = DiscoveryDiagnostic(
        "official",
        "index",
        "page_contract_changed",
        "official index did not match its expected structure",
        venue="Invented Venue",
        year=2026,
    )
    workflow = CorpusDiscoveryWorkflow(
        discoverer=lambda _: DiscoveryBatch(diagnostics=(diagnostic,)),
    )
    application = Application.for_test(
        app_root=tmp_path / "app",
        repository_root=tmp_path / "repository",
        corpus_discovery=workflow,
    )
    output = tmp_path / "output"

    exit_code = run_cli(
        ["discover", "corpus", "--spec", str(spec), "--output", str(output)],
        application=application,
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "shortfall"
    assert payload["shortfall"] == 1
    rows = [
        json.loads(line)
        for line in Path(payload["discovery_errors"]).read_text(encoding="utf-8").splitlines()
    ]
    assert rows == [
        {
            "error_code": "page_contract_changed",
            "message": "official index did not match its expected structure",
            "phase": "index",
            "provider_id": "official",
            "retryable": False,
            "url": "",
            "venue": "Invented Venue",
            "year": 2026,
        }
    ]
