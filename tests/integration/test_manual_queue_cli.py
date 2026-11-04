from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from pypdf import PdfWriter

from acquire_research_papers.acquisition.corpus import CorpusAcquisitionWorkflow
from acquire_research_papers.acquisition.manual_handoff import ManualSelectionWorkflow
from acquire_research_papers.acquisition.manual_queue import ManualQueueSession
from acquire_research_papers.cli import Application, run_cli
from acquire_research_papers.discovery.contracts import CandidateMetadata, VenueScope
from acquire_research_papers.selection import SelectionRecord, SelectionStore, build_selection_records


TITLES = ("Alpha Graph Study", "Beta Network Study", "Gamma Learning Study")


def make_selection(root: Path, titles=TITLES) -> SelectionStore:
    candidates = [
        CandidateMetadata(
            f"paper-{number}",
            title,
            2026,
            "Manual Journal",
            0.95,
            True,
            ("title", "abstract"),
            authors=("Ada Lovelace",),
            official_url=f"https://publisher.example/paper-{number}",
            abstract="Relevant abstract",
        )
        for number, title in enumerate(titles, start=1)
    ]
    records = build_selection_records(
        candidates,
        venues=(VenueScope("Manual Journal", short_name="MJ", publisher="Manual Publisher"),),
        delivery={"profile": "numbered", "naming_template": "Manual Publisher MJ/{number}.{ext}"},
    )
    return SelectionStore.write(root, {"name": "manual queue"}, records)


def unsupported(record: SelectionRecord, destination: Path) -> dict:
    return {"error_code": "unsupported_adapter", "message": "no adapter for publisher.example"}


def acquired(tmp_path: Path, titles=TITLES) -> tuple[SelectionStore, Path]:
    store = make_selection(tmp_path / "selection", titles)
    delivery = tmp_path / "delivery"
    result = CorpusAcquisitionWorkflow(acquirer=unsupported).run(store.manifest_path, delivery)
    assert result.manual_required == len(titles)
    return store, delivery


def write_pdf(path: Path, title: str, *, variant: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.add_metadata({"/Title": title, **({"/Subject": variant} if variant else {})})
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def write_bib(path: Path, title: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"@article{{k,title={{{title}}},author={{Lovelace, Ada}},year={{2026}},"
        "journal={Manual Journal}}",
        encoding="utf-8",
    )
    return path


def application(tmp_path: Path, opened: list[str] | None = None) -> Application:
    def opener(url: str) -> bool:
        if opened is not None:
            opened.append(url)
        return True

    return Application.for_test(
        app_root=tmp_path / "app",
        repository_root=tmp_path / "repository",
        manual_selection=ManualSelectionWorkflow(opener=opener),
    )


def ledger_states(delivery: Path) -> dict[str, str]:
    rows = [json.loads(line) for line in
            (delivery / "acquisition-manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    return {row["title"]: row["state"] for row in rows}


def queue_titles(delivery: Path) -> list[str]:
    path = delivery / "manual-download.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [row["title"] for row in csv.DictReader(handle)]


def test_queue_imports_every_pair_in_a_folder_and_updates_the_ledger(tmp_path, capsys):
    store, delivery = acquired(tmp_path)
    folder = tmp_path / "downloads"
    alpha_pdf = write_pdf(folder / "alpha.pdf", TITLES[0])
    write_bib(folder / "alpha.bib", TITLES[0])
    write_pdf(folder / "gamma.pdf", TITLES[2])
    write_bib(folder / "gamma.bib", TITLES[2])
    write_bib(folder / "beta.bib", TITLES[1])
    (folder / "notes.txt").write_text("not a citation", encoding="utf-8")
    original = alpha_pdf.read_bytes()

    exit_code = run_cli(
        ["manual-fetch", "--selection", str(store.manifest_path), "--queue",
         "--output", str(delivery), "--from", str(folder)],
        application=application(tmp_path),
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "partial"
    assert (payload["imported"], payload["remaining"], payload["delivered"]) == (2, 1, 2)
    statuses = {item["title"]: item["status"] for item in payload["items"]}
    assert statuses == {TITLES[0]: "imported", TITLES[1]: "waiting", TITLES[2]: "imported"}
    beta = next(item for item in payload["items"] if item["title"] == TITLES[1])
    assert "raw BibTeX but no matching PDF" in beta["message"]
    assert ledger_states(delivery) == {
        TITLES[0]: "delivered", TITLES[1]: "manual_required", TITLES[2]: "delivered"}
    assert queue_titles(delivery) == [TITLES[1]]
    assert alpha_pdf.read_bytes() == original

    write_pdf(folder / "beta.pdf", TITLES[1])
    exit_code = run_cli(
        ["manual-fetch", "--selection", str(store.manifest_path), "--queue",
         "--output", str(delivery), "--from", str(folder)],
        application=application(tmp_path),
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "complete"
    assert payload["manual_download"] is None
    assert [item["title"] for item in payload["items"]] == [TITLES[1]]
    assert not (delivery / "manual-download.csv").exists()

    def no_network(record, destination):
        pytest.fail("a verified manual import must not be acquired again")

    rerun = CorpusAcquisitionWorkflow(acquirer=no_network).run(store.manifest_path, delivery)
    assert rerun.complete


def test_watch_imports_pairs_in_any_order_and_counts_late_downloads(tmp_path):
    store = make_selection(tmp_path / "selection")
    records = store.records
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    clock = {"now": 0.0, "sleeps": 0}
    arrivals = {
        # While the session prompts for Alpha, the user downloads Gamma first.
        1: [(write_pdf, "gamma.pdf", TITLES[2]), (write_bib, "gamma.bib", TITLES[2])],
        4: [(write_pdf, "alpha.pdf", TITLES[0]), (write_bib, "alpha.bib", TITLES[0])],
    }

    def sleeper(seconds: float) -> None:
        clock["sleeps"] += 1
        clock["now"] += seconds
        for writer, name, title in arrivals.pop(clock["sleeps"], []):
            writer(downloads / name, title)

    delivered: list[str] = []
    opened: list[str] = []
    progress: list[str] = []
    session = ManualQueueSession(
        records,
        deliver=lambda record, selection: delivered.append(record.title),
        opener=lambda url: opened.append(url) or True,
        progress=progress.append,
        monotonic=lambda: clock["now"],
        sleeper=sleeper,
    )

    outcomes = session.watch(downloads, timeout_seconds=30, open_browser=True)

    assert delivered == [TITLES[2], TITLES[0]]
    assert {outcome.title: outcome.status for outcome in outcomes} == {
        TITLES[0]: "imported", TITLES[1]: "waiting", TITLES[2]: "imported"}
    # Gamma was imported before its turn, so only Alpha and Beta were opened.
    assert opened == [records[0].official_url, records[1].official_url]
    assert any("moving on" in line and TITLES[1] in line for line in progress)
    beta = next(outcome for outcome in outcomes if outcome.title == TITLES[1])
    assert "no matching PDF or raw BibTeX was found during this session" in beta.message


def test_files_present_before_the_session_are_ignored_by_watch(tmp_path):
    store = make_selection(tmp_path / "selection", TITLES[:1])
    downloads = tmp_path / "downloads"
    write_pdf(downloads / "old.pdf", TITLES[0])
    write_bib(downloads / "old.bib", TITLES[0])
    clock = {"now": 0.0}

    def sleeper(seconds: float) -> None:
        clock["now"] += seconds

    progress: list[str] = []
    session = ManualQueueSession(
        store.records,
        deliver=lambda record, selection: pytest.fail("pre-existing files must not be imported"),
        opener=lambda url: True,
        progress=progress.append,
        monotonic=lambda: clock["now"],
        sleeper=sleeper,
    )
    outcomes = session.watch(downloads, timeout_seconds=5, open_browser=False)
    assert outcomes[0].status == "waiting"
    assert "2 PDF or BibTeX files already there are ignored" in progress[0]


def test_distinct_valid_duplicates_leave_the_paper_for_an_explicit_import(tmp_path):
    store = make_selection(tmp_path / "selection", TITLES[:1])
    folder = tmp_path / "downloads"
    write_pdf(folder / "alpha.pdf", TITLES[0])
    write_pdf(folder / "alpha-again.pdf", TITLES[0], variant="second download")
    write_bib(folder / "alpha.bib", TITLES[0])
    session = ManualQueueSession(
        store.records,
        deliver=lambda record, selection: pytest.fail("an ambiguous paper must not be imported"),
        opener=lambda url: True,
    )
    (outcome,) = session.import_folder(folder)
    assert outcome.status == "ambiguous"
    assert "--key" in outcome.message


def test_a_file_matching_two_queued_papers_is_never_assigned(tmp_path):
    titles = ("Graph Study", "Graph Study Extended")
    store = make_selection(tmp_path / "selection", titles)
    folder = tmp_path / "downloads"
    # The longer title's PDF also contains the shorter title.
    write_pdf(folder / "extended.pdf", titles[1])
    write_bib(folder / "extended.bib", titles[1])
    session = ManualQueueSession(
        store.records,
        deliver=lambda record, selection: pytest.fail("a shared file must not be assigned"),
        opener=lambda url: True,
    )
    outcomes = {outcome.title: outcome for outcome in session.import_folder(folder)}
    assert outcomes[titles[1]].status == "waiting"
    assert "more than one paper in the queue" in outcomes[titles[1]].message


def test_queue_requires_a_finished_acquisition(tmp_path, capsys):
    store, delivery = acquired(tmp_path)
    manifest = delivery / "delivery-manifest.json"
    manifest.write_text(
        json.dumps({**json.loads(manifest.read_text(encoding="utf-8")), "status": "in_progress"}),
        encoding="utf-8",
    )
    exit_code = run_cli(
        ["manual-fetch", "--selection", str(store.manifest_path), "--queue",
         "--output", str(delivery), "--from", str(tmp_path)],
        application=application(tmp_path),
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 64
    assert "interrupted" in payload["message"]


@pytest.mark.parametrize("extra", [["--key", "abc"], ["--input", "10.1000/x"]])
def test_queue_rejects_single_paper_arguments(tmp_path, capsys, extra):
    store, delivery = acquired(tmp_path)
    exit_code = run_cli(
        ["manual-fetch", "--selection", str(store.manifest_path), "--queue",
         "--output", str(delivery), *extra],
        application=application(tmp_path),
    )
    assert exit_code == 64
    assert "--queue" in json.loads(capsys.readouterr().out)["message"]


def test_from_requires_queue(tmp_path, capsys):
    store, delivery = acquired(tmp_path)
    exit_code = run_cli(
        ["manual-fetch", "--selection", str(store.manifest_path), "--key",
         store.records[0].selection_id, "--output", str(delivery), "--from", str(tmp_path)],
        application=application(tmp_path),
    )
    assert exit_code == 64
    assert "--from requires --queue" in json.loads(capsys.readouterr().out)["message"]
