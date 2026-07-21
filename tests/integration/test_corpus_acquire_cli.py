from __future__ import annotations

import csv
import json
from pathlib import Path

from acquire_research_papers.acquisition.corpus import CorpusAcquisitionWorkflow
from acquire_research_papers.artifacts import sha256_file
from acquire_research_papers.cli import Application, run_cli
from acquire_research_papers.discovery.contracts import CandidateMetadata, VenueScope
from acquire_research_papers.selection import SelectionStore, build_selection_records


def make_selection(root: Path) -> SelectionStore:
    candidates = (
        CandidateMetadata(
            "blocked",
            "Blocked Paper",
            2026,
            "Invented Venue",
            0.95,
            True,
            ("title", "abstract"),
            doi="10.1000/blocked",
            official_url="https://publisher.example/blocked",
            abstract="Relevant abstract",
        ),
        CandidateMetadata(
            "available",
            "Available Paper",
            2026,
            "Invented Venue",
            0.94,
            True,
            ("title", "abstract"),
            doi="10.1000/available",
            official_url="https://publisher.example/available",
            abstract="Relevant abstract",
        ),
    )
    records = build_selection_records(
        candidates,
        venues=(
            VenueScope(
                "Invented Venue",
                short_name="IV",
                publisher="Invented Society",
            ),
        ),
        delivery={
            "profile": "numbered",
            "naming_template": "Invented Society IV/{number}.{ext}",
        },
    )
    return SelectionStore.write(
        root,
        {
            "mode": "corpus",
            "name": "acquisition test",
            "target": {"minimum": 1, "preferred": 2, "maximum": 2},
        },
        records,
    )


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


def test_acquire_corpus_separates_delivered_and_manual_states(
    tmp_path: Path,
    capsys,
) -> None:
    selection = make_selection(tmp_path / "selection")
    selected_before = selection.selected_path.read_bytes()
    calls: list[str] = []

    def acquirer(record, output: Path):
        calls.append(record.key)
        if record.key == "blocked":
            return {
                "status": "manual_required",
                "error_code": "access_required",
                "message": "institutional login is incomplete",
            }
        return delivered_outcome(record, output)

    workflow = CorpusAcquisitionWorkflow(acquirer=acquirer)
    application = Application.for_test(
        app_root=tmp_path / "app",
        repository_root=tmp_path / "repository",
        corpus_acquisition=workflow,
    )
    output = tmp_path / "delivery"

    exit_code = run_cli(
        [
            "acquire",
            "corpus",
            "--selection",
            str(selection.manifest_path),
            "--output",
            str(output),
        ],
        application=application,
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert calls == ["blocked", "available"]
    assert payload["status"] == "partial"
    assert payload["delivered"] == 1
    assert payload["manual_required"] == 1
    assert payload["retryable"] == 0
    ledger = [
        json.loads(line)
        for line in Path(payload["acquisition_manifest"])
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [row["state"] for row in ledger] == ["manual_required", "delivered"]
    with Path(payload["manual_download"]).open(encoding="utf-8-sig", newline="") as handle:
        manual = list(csv.DictReader(handle))
    assert manual[0]["selection_id"] == selection.records[0].selection_id
    assert manual[0]["target_pdf"] == "Invented Society IV/1.pdf"
    with Path(payload["retryable_downloads"]).open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        assert list(csv.DictReader(handle)) == []
    assert selection.selected_path.read_bytes() == selected_before


def test_acquire_corpus_reuses_only_hash_verified_delivery(
    tmp_path: Path,
    capsys,
) -> None:
    selection = make_selection(tmp_path / "selection")
    calls: list[str] = []

    def acquirer(record, output: Path):
        calls.append(record.key)
        if record.key == "blocked":
            return {"error_code": "network_transient", "message": "try later"}
        return delivered_outcome(record, output)

    workflow = CorpusAcquisitionWorkflow(acquirer=acquirer)
    application = Application.for_test(
        app_root=tmp_path / "app",
        repository_root=tmp_path / "repository",
        corpus_acquisition=workflow,
    )
    output = tmp_path / "delivery"
    args = [
        "acquire",
        "corpus",
        "--selection",
        str(selection.manifest_path),
        "--output",
        str(output),
    ]

    assert run_cli(args, application=application) == 0
    capsys.readouterr()
    assert calls == ["blocked", "available"]
    calls.clear()

    assert run_cli(args, application=application) == 0
    payload = json.loads(capsys.readouterr().out)

    assert calls == ["blocked"]
    assert payload["delivered"] == 1
    assert payload["retryable"] == 1


def test_acquire_corpus_rejects_modified_frozen_selection(
    tmp_path: Path,
    capsys,
) -> None:
    selection = make_selection(tmp_path / "selection")
    selection.selected_path.write_text("{}\n", encoding="utf-8")
    application = Application.for_test(
        app_root=tmp_path / "app",
        repository_root=tmp_path / "repository",
        corpus_acquisition=CorpusAcquisitionWorkflow(acquirer=lambda *_: {}),
    )

    exit_code = run_cli(
        [
            "acquire",
            "corpus",
            "--selection",
            str(selection.manifest_path),
            "--output",
            str(tmp_path / "delivery"),
        ],
        application=application,
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 64
    assert payload["error_code"] == "invalid_input"
    assert "SHA-256" in payload["message"]
