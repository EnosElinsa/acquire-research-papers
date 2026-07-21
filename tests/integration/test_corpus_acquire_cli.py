from __future__ import annotations

import csv
import json
from pathlib import Path

from acquire_research_papers.acquisition.corpus import CorpusAcquisitionWorkflow
from acquire_research_papers.acquisition.base import AcquiredPair, SourceAdapter, SourceDocument
from acquire_research_papers.artifacts import sha256_file
from acquire_research_papers.cli import Application, run_cli
from acquire_research_papers.discovery.contracts import CandidateMetadata, VenueScope
from acquire_research_papers.models import PaperMetadata
from acquire_research_papers.selection import SelectionStore, build_selection_records


def make_selection(
    root: Path,
    *,
    publisher_host: str = "publisher.example",
) -> SelectionStore:
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
            official_url=f"https://{publisher_host}/blocked",
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
            official_url=f"https://{publisher_host}/available",
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


def test_selected_acquisition_prefers_the_frozen_official_url(tmp_path: Path) -> None:
    selection = make_selection(tmp_path / "selection")

    class RecordingAdapter(SourceAdapter):
        name = "recording"
        production_hosts = frozenset({"publisher.example"})

        def __init__(self) -> None:
            self.references: list[str] = []

        def resolve(self, value: str) -> SourceDocument:
            self.references.append(value)
            return SourceDocument(
                metadata=PaperMetadata(
                    title="Blocked Paper",
                    authors=("Ada Lovelace",),
                    year=2026,
                    venue="Invented Venue",
                    doi="10.1000/blocked",
                    publisher="Invented Society",
                    landing_url=value,
                ),
                pdf_url="https://publisher.example/blocked.pdf",
                bibtex_url="https://publisher.example/blocked.bib",
                allowed_hosts=frozenset({"publisher.example"}),
            )

        def acquire(self, document: SourceDocument) -> AcquiredPair:
            return AcquiredPair(
                document=document,
                pdf_bytes=b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n",
                bibtex_text=(
                    "@article{k,title={Blocked Paper},author={Lovelace, Ada},"
                    "year={2026},journal={Invented Venue},doi={10.1000/blocked}}"
                ),
            )

    adapter = RecordingAdapter()
    application = Application.for_test(
        app_root=tmp_path / "app",
        repository_root=tmp_path / "repository",
        adapter=adapter,
    )

    result = application.acquire_selected(selection.records[0], tmp_path / "delivery")

    assert result["status"] == "delivered"
    assert adapter.references == [selection.records[0].official_url]


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
    assert payload["paper_manifest"] == str(output / "paper-manifest.csv")
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
    with (output / "paper-manifest.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        paper_manifest = list(csv.DictReader(handle))
    assert paper_manifest[0] == {
        "folder": "Invented Society IV",
        "number": "1",
        "title": "Blocked Paper",
        "year": "2026",
        "venue": "Invented Venue",
        "doi": "10.1000/blocked",
        "official_landing_url": "https://publisher.example/blocked",
        "official_pdf_url": "",
        "official_bibtex_url": "",
        "keywords": "",
        "state": "manual_required",
        "pdf": "Invented Society IV/1.pdf",
        "bibtex": "Invented Society IV/1.bib",
    }
    assert paper_manifest[1]["state"] == "delivered"
    assert paper_manifest[1]["pdf"] == "Invented Society IV/2.pdf"
    assert selection.selected_path.read_bytes() == selected_before


def test_acquire_corpus_defers_exact_hosts_without_calling_acquirer(
    tmp_path: Path,
    capsys,
) -> None:
    selection = make_selection(tmp_path / "selection")
    calls: list[str] = []

    def acquirer(record, output: Path):
        calls.append(record.key)
        return delivered_outcome(record, output)

    application = Application.for_test(
        app_root=tmp_path / "app",
        repository_root=tmp_path / "repository",
        corpus_acquisition=CorpusAcquisitionWorkflow(acquirer=acquirer),
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
            "--defer-host",
            "PUBLISHER.EXAMPLE",
        ],
        application=application,
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert calls == []
    assert payload["manual_required"] == 2
    assert payload["delivered"] == 0
    ledger = [
        json.loads(line)
        for line in Path(payload["acquisition_manifest"])
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert {row["error_code"] for row in ledger} == {"access_required"}
    assert {row["message"] for row in ledger} == {
        "publisher host deferred for this run: publisher.example"
    }


def test_acquire_corpus_rejects_non_hostname_defer_values(
    tmp_path: Path,
    capsys,
) -> None:
    selection = make_selection(tmp_path / "selection")
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
            "--defer-host",
            "https://publisher.example/path?Signature=synthetic-secret",
        ],
        application=application,
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 64
    assert payload["error_code"] == "invalid_input"
    assert "exact hostname" in payload["message"]
    assert "Signature" not in payload["message"]
    assert "synthetic-secret" not in payload["message"]


def test_defer_host_does_not_match_a_subdomain(
    tmp_path: Path,
    capsys,
) -> None:
    selection = make_selection(
        tmp_path / "selection",
        publisher_host="papers.example.com",
    )
    calls: list[str] = []

    def acquirer(record, output: Path):
        calls.append(record.key)
        return delivered_outcome(record, output)

    application = Application.for_test(
        app_root=tmp_path / "app",
        repository_root=tmp_path / "repository",
        corpus_acquisition=CorpusAcquisitionWorkflow(acquirer=acquirer),
    )

    exit_code = run_cli(
        [
            "acquire",
            "corpus",
            "--selection",
            str(selection.manifest_path),
            "--output",
            str(tmp_path / "delivery"),
            "--defer-host",
            "example.com",
        ],
        application=application,
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert calls == ["blocked", "available"]
    assert payload["delivered"] == 2
    assert payload["manual_required"] == 0


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
