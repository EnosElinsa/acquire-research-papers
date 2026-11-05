from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

from acquire_research_papers.http import HttpStatusError

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("check_sources", ROOT / "scripts" / "check_sources.py")
check_sources = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = check_sources
spec.loader.exec_module(check_sources)


def report(pauses: list[float] | None = None):
    lines: list[str] = []
    sleeper = pauses.append if pauses is not None else (lambda seconds: None)
    return check_sources.Report(progress=lines.append, retry_pause=7, sleeper=sleeper), lines


def test_a_transient_failure_is_retried_once_and_marked():
    pauses: list[float] = []
    checks, lines = report(pauses)
    answers = iter([check_sources.Outcome("x", "busy", False, transient=True),
                    check_sources.Outcome("x", "fine", True)])

    checks.run("index X", lambda: next(answers), expected="x")

    result = checks.result()
    assert pauses == [7]
    assert result["status"] == "passed"
    assert result["retried"] == ["index X"]
    assert lines[-1] == "ok   index X: fine (after a retry)"


def test_a_lasting_transient_failure_is_an_upstream_error_and_does_not_fail_the_run():
    checks, lines = report()
    calls = []

    def attempt():
        calls.append(1)
        raise HttpStatusError(520, "https://ojs.aaai.org/x?api_key=secret")

    checks.run("fetch AAAI DOI", attempt, expected="delivered")

    result = checks.result()
    assert len(calls) == 2
    assert result["status"] == "passed" and result["failed"] == []
    assert result["upstream_errors"] == ["fetch AAAI DOI"]
    assert result["checks"][0]["observed"] == "error: HTTP 520 for ojs.aaai.org"
    assert lines[-1].startswith("UPST fetch AAAI DOI")


def test_a_contract_failure_fails_at_once_without_a_retry():
    checks, _ = report()
    calls = []

    def attempt():
        calls.append(1)
        raise HttpStatusError(404, "https://ijcai.org/proceedings/2023")

    checks.run("index IJCAI 2023", attempt, expected=">= 600 listed")

    assert len(calls) == 1
    assert checks.result()["failed"] == ["index IJCAI 2023"]


def fake_index(read: int, codes: tuple[str, ...]):
    batch = SimpleNamespace(
        candidates=[SimpleNamespace(abstract="Abstract") for _ in range(read)],
        coverage=[SimpleNamespace(records_recognized=2353)],
        diagnostics=[SimpleNamespace(error_code=code) for code in codes])
    provider = SimpleNamespace(discover=lambda request: batch)
    return check_sources.IndexCase("CVPR", 2023, 2000, lambda: provider)


def test_an_index_sample_page_that_was_not_read_fails_the_check_and_is_retried():
    outcome = check_sources._index_outcome(fake_index(2, ("network_transient",)), 3)
    assert (outcome.passed, outcome.transient) == (False, True)
    assert check_sources._index_outcome(fake_index(3, ()), 3).passed is True


def test_error_text_keeps_only_the_host_of_each_url():
    text = check_sources._without_urls(
        "HTTP 500 for https://api.openalex.org/sources/S1?api_key=k3y and 'http://a.example/b'")
    assert text == "HTTP 500 for api.openalex.org and 'a.example'"
    assert "k3y" not in text


def test_fetch_checks_use_a_fresh_directory_per_attempt(tmp_path):
    checks, _ = report()
    outputs = []
    answers = iter([(75, {"status": "error", "error_code": "network_transient",
                          "message": "HTTP 503 from proceedings.mlr.press"}),
                    (0, {"status": "delivered"}),
                    (78, {"status": "error", "error_code": "contract_error",
                          "message": "official BibTeX missing at https://x.example/p?q=1"})])

    def fetch(reference, output):
        outputs.append(output)
        return next(answers)

    check_sources.check_fetches(checks, fetch=fetch, workspace=tmp_path,
                                cases=(("PMLR URL", "p"), ("ACL DOI", "a")))

    rows = checks.result()["checks"]
    assert outputs == [tmp_path / "PMLR-URL" / "attempt-1", tmp_path / "PMLR-URL" / "attempt-2",
                       tmp_path / "ACL-DOI" / "attempt-1"]
    assert [row["status"] for row in rows] == ["passed", "failed"]
    assert rows[1]["observed"] == {"outcome": "contract_error",
                                   "message": "official BibTeX missing at x.example"}


def test_the_weekly_fetches_are_the_smoke_fetches_that_need_no_subscription():
    labels = [label for label, _ in check_sources.open_access_fetches()]
    assert labels == ["ACL DOI", "AAAI DOI", "NeurIPS URL", "PMLR URL", "CVF URL", "IJCAI DOI"]
