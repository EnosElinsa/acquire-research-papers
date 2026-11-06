"""fetch --input-file, IEEE automatic retry, the flat layout, and --result-file."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from acquire_research_papers.acquisition.adapters.ieee import (
    IeeeBridgeError,
    IeeeTransientError,
    IeeeXploreAdapter,
)
from acquire_research_papers.acquisition.base import AccessRequired
from acquire_research_papers.acquisition.fetch_list import (
    LEDGER_FILE,
    FetchListWorkflow,
    input_host,
    read_input_list,
)
from acquire_research_papers.acquisition.adapters.ieee import IeeeBridgeResult
from acquire_research_papers.cli import Application, run_cli
from acquire_research_papers.delivery import DeliveryResult, GenericDelivery
from acquire_research_papers.http import NetworkTransient

PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"


def test_the_list_file_skips_comments_blank_lines_and_repeats(tmp_path: Path) -> None:
    listing = tmp_path / "dois.txt"
    listing.write_text("\ufeff# surveys\n10.1109/TRO.2024.1\n\nhttps://doi.org/10.1109/tro.2024.1\n"
                       "  https://ieeexplore.ieee.org/document/2/  \n", encoding="utf-8")
    assert read_input_list(listing) == ["10.1109/TRO.2024.1",
                                        "https://ieeexplore.ieee.org/document/2/"]
    (tmp_path / "empty.txt").write_text("# nothing\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no DOI"):
        read_input_list(tmp_path / "empty.txt")


def test_inputs_are_grouped_by_their_publisher_host_offline() -> None:
    assert input_host("10.1109/TRO.2024.1") == "ieeexplore.ieee.org"
    assert input_host("https://doi.org/10.1109/x") == "ieeexplore.ieee.org"
    assert input_host("https://ieeexplore.ieee.org/document/1") == "ieeexplore.ieee.org"


def test_every_paper_gets_one_ledger_row_and_failures_do_not_stop_the_list(tmp_path):
    def fetch(value: str, output: Path) -> DeliveryResult:
        if value.endswith("refused"):
            raise AccessRequired("institution refused this paper")
        if value.endswith("flaky"):
            raise NetworkTransient("timed out")
        folder = output / value.rsplit("/", 1)[-1]
        folder.mkdir(parents=True)
        for name, data in (("paper.pdf", PDF), ("citation.bib", b"@article{k,}"),
                           ("provenance.json", b"{}")):
            (folder / name).write_bytes(data)
        return DeliveryResult(folder / "paper.pdf", folder / "citation.bib",
                              folder / "provenance.json")

    events: list[dict] = []
    result = FetchListWorkflow(fetch=fetch, progress=events.append, sleeper=lambda s: None).run(
        ["10.1109/one", "10.1109/refused", "10.1109/flaky"], tmp_path / "out")

    rows = [json.loads(line) for line in
            (tmp_path / "out" / LEDGER_FILE).read_text(encoding="utf-8").splitlines()]
    assert [row["state"] for row in rows] == ["delivered", "manual_required", "retryable"]
    assert rows[0]["pdf_sha256"] and rows[1]["error_code"] == "access_required"
    assert (result["status"], result["delivered"], result["total"]) == ("partial", 1, 3)
    assert result["next_actions"][0]["command"].startswith(
        "arp manual-fetch --input 10.1109/refused --output ")
    assert result["next_actions"][-1]["action"] == "rerun"
    assert [event["event"] for event in events] == ["paper_started", "paper_finished"] * 3


def test_an_institution_login_failure_pauses_the_host_for_the_rest_of_the_list(tmp_path):
    calls = []

    def fetch(value: str, output: Path) -> DeliveryResult:
        calls.append(value)
        raise IeeeBridgeError("carsi-login", "login did not complete")

    result = FetchListWorkflow(fetch=fetch, sleeper=lambda s: None).run(
        ["10.1109/a", "10.1109/b"], tmp_path / "out")

    assert calls == ["10.1109/a"]  # credentials are not resubmitted paper by paper
    assert [item["error_code"] for item in result["items"]] == ["access_required"] * 2


def test_a_stop_keeps_finished_rows_and_reports_where_the_list_stopped(tmp_path):
    def fetch(value: str, output: Path) -> DeliveryResult:
        raise KeyboardInterrupt

    result = FetchListWorkflow(fetch=fetch, sleeper=lambda s: None).run(
        ["10.1109/a", "10.1109/b"], tmp_path / "out")

    assert result["interrupted"] and result["not_attempted"] == 2
    assert result["next_actions"] == [{"action": "rerun", "reason": "interrupted",
                                       "message": result["next_actions"][0]["message"]}]


def test_fetch_input_file_runs_the_list_through_the_cli(tmp_path: Path, capsys) -> None:
    listing = tmp_path / "list.txt"
    listing.write_text("A title is not a reference\n", encoding="utf-8")
    application = Application.for_test(app_root=tmp_path / "app",
                                       repository_root=tmp_path / "repository")

    code = run_cli(["fetch", "--input-file", str(listing), "--output", str(tmp_path / "out")],
                   application=application)

    result = json.loads(capsys.readouterr().out)
    assert code == 0
    assert (result["status"], result["contract_error"], result["total"]) == ("partial", 1, 1)
    assert Path(result["fetch_ledger"]).is_file()


def test_input_and_input_file_are_exclusive(tmp_path: Path, capsys) -> None:
    with pytest.raises(SystemExit):
        run_cli(["fetch", "--input", "x", "--input-file", "y", "--output", str(tmp_path)])


class Bridge:
    def __init__(self, failures: list[Exception]) -> None:
        self.failures = failures
        self.calls = 0

    def retrieve(self, reference: str) -> IeeeBridgeResult:
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return IeeeBridgeResult(
            title="Verified Paper", authors=("Ada Lovelace",), year=2026, venue="Test Venue",
            doi="10.1109/test.1", landing_url="https://ieeexplore.ieee.org/document/1",
            pdf_url="https://ieeexplore.ieee.org/stamp/1", bibtex_url=(
                "https://ieeexplore.ieee.org/xpl/downloadCitations"),
            pdf_bytes=PDF, bibtex="@article{k,title={Verified Paper},author={Lovelace, Ada},"
                                  "year={2026},journal={Test Venue},doi={10.1109/test.1}}")


@pytest.mark.parametrize("failure, code", [
    (IeeeTransientError("pdf-request-timeout", "PDF request timed out"), "network_transient"),
    (IeeeBridgeError("automation", "IEEE automation failed (TimeoutError)"), "automation_error"),
])
def test_ieee_retries_a_timed_out_step_once_and_records_it(tmp_path, failure, code) -> None:
    bridge = Bridge([failure])
    delays: list[float] = []
    adapter = IeeeXploreAdapter(bridge, sleeper=delays.append)

    document = adapter.resolve("https://ieeexplore.ieee.org/document/1")
    pair = adapter.acquire(document)
    result = GenericDelivery(tmp_path / "out").deliver(pair=pair, paper_id="paper-1")

    assert bridge.calls == 2 and delays == [5.0]
    provenance = json.loads(result.provenance.read_text(encoding="utf-8"))
    assert provenance["acquisition_retries"] == [
        {"attempt": 1, "error_code": code, "phase": failure.phase}]


def test_ieee_does_not_repeat_a_login_failure_or_retry_twice() -> None:
    login = Bridge([IeeeBridgeError("carsi-login", "login did not complete")])
    with pytest.raises(IeeeBridgeError):
        IeeeXploreAdapter(login, sleeper=lambda s: None).resolve(
            "https://ieeexplore.ieee.org/document/1")
    assert login.calls == 1
    twice = Bridge([IeeeTransientError("pdf-request-timeout", "a"),
                    IeeeTransientError("pdf-request-timeout", "b")])
    with pytest.raises(NetworkTransient):
        IeeeXploreAdapter(twice, sleeper=lambda s: None).resolve(
            "https://ieeexplore.ieee.org/document/1")
    assert twice.calls == 2


def test_the_flat_layout_puts_short_named_files_directly_in_the_output(tmp_path, verified_pair):
    long_title = replace(verified_pair.document.metadata, title="A " + "Very Long Title " * 10)
    pair = replace(verified_pair, document=replace(verified_pair.document, metadata=long_title))
    # The publisher's BibTeX must still name the same title for the pair to verify.
    pair = replace(pair, bibtex_text=pair.bibtex_text.replace(
        "Verified Paper", long_title.title.strip()))

    result = GenericDelivery(tmp_path / "out", layout="flat").deliver(
        pair=pair, paper_id="0123456789abcdef")

    assert {path.parent for path in (result.pdf, result.bibtex, result.provenance)} == {
        (tmp_path / "out").resolve()}
    # The title part is cut at 40 characters.
    assert result.pdf.name == "A_Very_Long_Title_Very_Long_Title_Very_L--0123456789ab.pdf"
    assert result.bibtex.name.endswith("--0123456789ab.bib")
    assert result.provenance.name.endswith("--0123456789ab.provenance.json")


def test_result_file_receives_the_printed_result(tmp_path: Path, capsys) -> None:
    application = Application.for_test(app_root=tmp_path / "app",
                                       repository_root=tmp_path / "repository")
    target = tmp_path / "results" / "fetch.json"

    code = run_cli(["fetch", "--input", "A title", "--output", str(tmp_path / "out"),
                    "--result-file", str(target)], application=application)

    printed = capsys.readouterr().out
    assert code == 64
    assert json.loads(target.read_text(encoding="utf-8")) == json.loads(printed)
    assert json.loads(printed)["error_code"] == "invalid_input"
