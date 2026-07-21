from __future__ import annotations

import json
from pathlib import Path

from pypdf import PdfWriter

from acquire_research_papers.acquisition.manual_handoff import ManualSelectionWorkflow
from acquire_research_papers.cli import Application, run_cli
from acquire_research_papers.discovery.contracts import CandidateMetadata, VenueScope
from acquire_research_papers.selection import SelectionRecord, SelectionStore, build_selection_records


def make_selection(root: Path) -> tuple[SelectionStore, SelectionRecord]:
    candidate = CandidateMetadata(
        "manual",
        "Manual Paper",
        2026,
        "Manual Journal",
        0.95,
        True,
        ("title", "abstract"),
        authors=("Ada Lovelace",),
        official_url="https://publisher.example/manual",
        abstract="Relevant abstract",
    )
    records = build_selection_records(
        [candidate],
        venues=(
            VenueScope(
                "Manual Journal",
                short_name="MJ",
                publisher="Manual Publisher",
            ),
        ),
        delivery={
            "profile": "numbered",
            "naming_template": "Manual Publisher MJ/{number}.{ext}",
        },
    )
    store = SelectionStore.write(root, {"name": "manual"}, records)
    return store, records[0]


def write_matching_pair(root: Path, record: SelectionRecord) -> tuple[Path, Path]:
    root.mkdir(parents=True)
    pdf = root / "manual.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.add_metadata({"/Title": record.title})
    with pdf.open("wb") as handle:
        writer.write(handle)
    bib = root / "manual.bib"
    bib.write_text(
        "@article{manual,title={Manual Paper},author={Lovelace, Ada},"
        "year={2026},journal={Manual Journal}}",
        encoding="utf-8",
    )
    return pdf, bib


def configured_application(tmp_path: Path) -> Application:
    return Application.for_test(
        app_root=tmp_path / "app",
        repository_root=tmp_path / "repository",
        manual_selection=ManualSelectionWorkflow(opener=lambda _: True),
    )


def test_manual_fetch_selection_imports_to_reserved_paths(
    tmp_path: Path,
    capsys,
) -> None:
    store, record = make_selection(tmp_path / "selection")
    pdf, bib = write_matching_pair(tmp_path / "downloads", record)
    original_pdf = pdf.read_bytes()
    original_bib = bib.read_bytes()
    application = configured_application(tmp_path)

    exit_code = run_cli(
        [
            "manual-fetch",
            "--selection",
            str(store.manifest_path),
            "--key",
            record.selection_id,
            "--output",
            str(tmp_path / "delivery"),
            "--pdf",
            str(pdf),
            "--bibtex",
            str(bib),
            "--no-open",
        ],
        application=application,
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert Path(payload["pdf"]) == (tmp_path / "delivery" / record.relative_pdf).resolve()
    assert Path(payload["bibtex"]) == (
        tmp_path / "delivery" / record.relative_bibtex
    ).resolve()
    assert pdf.read_bytes() == original_pdf
    assert bib.read_bytes() == original_bib
    provenance = json.loads(Path(payload["provenance"]).read_text(encoding="utf-8"))
    assert provenance["selection_id"] == record.selection_id
    assert provenance["acquisition_method"] == "manual_publisher_download"


def test_manual_fetch_verifies_selection_before_reading_local_sources(
    tmp_path: Path,
    capsys,
) -> None:
    store, record = make_selection(tmp_path / "selection")
    store.selected_path.write_bytes(store.selected_path.read_bytes() + b" ")
    application = configured_application(tmp_path)

    exit_code = run_cli(
        [
            "manual-fetch",
            "--selection",
            str(store.manifest_path),
            "--key",
            record.selection_id,
            "--output",
            str(tmp_path / "delivery"),
            "--pdf",
            str(tmp_path / "missing.pdf"),
            "--bibtex",
            str(tmp_path / "missing.bib"),
            "--no-open",
        ],
        application=application,
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 64
    assert payload["error_code"] == "invalid_input"
    assert "selection SHA-256 mismatch" in payload["message"]


def test_manual_fetch_selection_requires_exact_selection_id(
    tmp_path: Path,
    capsys,
) -> None:
    store, _ = make_selection(tmp_path / "selection")
    application = configured_application(tmp_path)

    exit_code = run_cli(
        [
            "manual-fetch",
            "--selection",
            str(store.manifest_path),
            "--key",
            "missing-selection-id",
            "--output",
            str(tmp_path / "delivery"),
            "--no-open",
        ],
        application=application,
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 64
    assert payload["error_code"] == "invalid_input"
    assert "selection ID" in payload["message"]
