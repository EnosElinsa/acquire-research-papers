import json
from pathlib import Path

import pytest

from acquire_research_papers.acquisition.adapters.acl import AclAnthologyAdapter
from acquire_research_papers.acquisition.adapters.ieee import IeeeBridgeError
from acquire_research_papers.acquisition.base import AcquiredPair, SourceAdapter, SourceDocument
from acquire_research_papers.cli import Application, run_cli
from acquire_research_papers.http import NetworkTransient
from acquire_research_papers.models import PaperMetadata


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_fetch_cli_emits_one_json_object(fixture_server, tmp_path, capsys) -> None:
    fixture_server.serve_text(
        "/2025.acl-long.1/",
        (FIXTURES / "acl" / "paper.html").read_text(encoding="utf-8"),
    )
    fixture_server.serve_bytes(
        "/2025.acl-long.1.pdf",
        b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n",
        "application/pdf",
    )
    fixture_server.serve_text(
        "/2025.acl-long.1.bib",
        "@inproceedings{k,title={A Verified ACL Paper},"
        "author={Lovelace, Ada and Turing, Alan},year={2025},"
        "booktitle={Proceedings of ACL 2025 (Volume 1: Long Papers)},"
        "doi={10.18653/v1/2025.acl-long.1}}",
        "application/x-bibtex",
    )
    application = Application.for_test(
        app_root=tmp_path / "app",
        repository_root=tmp_path / "repository",
        adapter=AclAnthologyAdapter(
            client=fixture_server.client,
            production_hosts={fixture_server.host},
        ),
    )
    exit_code = run_cli(
        [
            "fetch",
            "--input",
            fixture_server.url("/2025.acl-long.1/"),
            "--output",
            str(tmp_path / "out"),
        ],
        application=application,
    )
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert stdout.count("\n") == 1
    assert exit_code == 0
    assert payload["status"] == "delivered"
    assert Path(payload["pdf"]).is_file()
    assert Path(payload["bibtex"]).is_file()


def test_fetch_cli_classifies_ambiguous_title(tmp_path, capsys) -> None:
    application = Application.for_test(
        app_root=tmp_path / "app",
        repository_root=tmp_path / "repository",
    )
    exit_code = run_cli(
        ["fetch", "--input", "A paper title", "--output", str(tmp_path / "out")],
        application=application,
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 64
    assert payload["status"] == "error"
    assert payload["error_code"] == "invalid_input"


class NetworkFailureAdapter(SourceAdapter):
    name = "network-failure"
    production_hosts = frozenset({"publisher.example"})

    def resolve(self, value):
        raise NetworkTransient("network retries exhausted")

    def acquire(self, document):
        raise AssertionError("unreachable")


def test_fetch_cli_classifies_exhausted_network_retry(tmp_path, capsys) -> None:
    application = Application.for_test(
        app_root=tmp_path / "app",
        repository_root=tmp_path / "repository",
        adapter=NetworkFailureAdapter(),
    )
    exit_code = run_cli(
        [
            "fetch",
            "--input",
            "https://publisher.example/paper",
            "--output",
            str(tmp_path / "out"),
        ],
        application=application,
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 75
    assert payload["status"] == "error"
    assert payload["error_code"] == "network_transient"


class InstitutionalFailureAdapter(SourceAdapter):
    name = "institutional-failure"
    production_hosts = frozenset({"ieeexplore.ieee.org"})

    def resolve(self, value):
        raise IeeeBridgeError(
            "download-after-auth",
            "IEEE did not return a PDF after institutional authentication",
        )

    def acquire(self, document):
        raise AssertionError("unreachable")


def test_fetch_cli_classifies_uncovered_ieee_item_as_access_required(tmp_path, capsys) -> None:
    application = Application.for_test(
        app_root=tmp_path / "app",
        repository_root=tmp_path / "repository",
        adapter=InstitutionalFailureAdapter(),
    )
    exit_code = run_cli(
        [
            "fetch",
            "--input",
            "https://ieeexplore.ieee.org/document/1",
            "--output",
            str(tmp_path / "out"),
        ],
        application=application,
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 69
    assert payload["status"] == "error"
    assert payload["error_code"] == "access_required"


class InstitutionProfileMismatchAdapter(SourceAdapter):
    name = "institution-profile-mismatch"
    production_hosts = frozenset({"ieeexplore.ieee.org"})

    def resolve(self, value):
        raise IeeeBridgeError(
            "institution-login",
            "configured institution login fields did not match the page",
        )

    def acquire(self, document):
        raise AssertionError("unreachable")


def test_fetch_cli_classifies_institution_profile_mismatch_as_access_required(
    tmp_path,
    capsys,
) -> None:
    application = Application.for_test(
        app_root=tmp_path / "app",
        repository_root=tmp_path / "repository",
        adapter=InstitutionProfileMismatchAdapter(),
    )
    exit_code = run_cli(
        [
            "fetch",
            "--input",
            "https://ieeexplore.ieee.org/document/2",
            "--output",
            str(tmp_path / "out"),
        ],
        application=application,
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 69
    assert payload["status"] == "error"
    assert payload["error_code"] == "access_required"


@pytest.mark.parametrize(
    "phase",
    [
        "attribute-release-controls",
        "attribute-release-required",
        "institutional-return",
    ],
)
def test_fetch_cli_classifies_institutional_return_phases_as_access_required(
    tmp_path,
    capsys,
    phase,
) -> None:
    class InstitutionalReturnAdapter(SourceAdapter):
        name = "institutional-return"
        production_hosts = frozenset({"ieeexplore.ieee.org"})

        def resolve(self, value):
            raise IeeeBridgeError(phase, "institutional user action is required")

        def acquire(self, document):
            raise AssertionError("unreachable")

    application = Application.for_test(
        app_root=tmp_path / "app",
        repository_root=tmp_path / "repository",
        adapter=InstitutionalReturnAdapter(),
    )
    exit_code = run_cli(
        [
            "fetch",
            "--input",
            "https://ieeexplore.ieee.org/document/3",
            "--output",
            str(tmp_path / "out"),
        ],
        application=application,
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 69
    assert payload["error_code"] == "access_required"


class CountingAdapter(SourceAdapter):
    name = "counting"
    production_hosts = frozenset({"publisher.example"})

    def __init__(self) -> None:
        self.resolve_calls = 0
        self.acquire_calls = 0

    def resolve(self, value):
        self.resolve_calls += 1
        return SourceDocument(
            metadata=PaperMetadata(
                title="A Durable Cached Paper",
                authors=("Ada Lovelace", "Alan Turing"),
                year=2026,
                venue="Journal of Durable Tests",
                doi="10.1000/durable-cache",
                publisher="Example Publisher",
                landing_url="https://publisher.example/paper",
            ),
            pdf_url="https://publisher.example/paper.pdf",
            bibtex_url="https://publisher.example/paper.bib",
            allowed_hosts=frozenset({"publisher.example"}),
        )

    def acquire(self, document):
        self.acquire_calls += 1
        return AcquiredPair(
            document=document,
            pdf_bytes=b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n",
            bibtex_text=(
                "@article{k,title={A Durable Cached Paper},"
                "author={Lovelace, Ada and Turing, Alan},year={2026},"
                "journal={Journal of Durable Tests},doi={10.1000/durable-cache}}"
            ),
        )


def test_fetch_reuses_verified_delivery_across_application_restarts(tmp_path, capsys) -> None:
    app_root = tmp_path / "app"
    repository = tmp_path / "repository"
    output = tmp_path / "out"
    first_adapter = CountingAdapter()
    first = Application.for_test(
        app_root=app_root,
        repository_root=repository,
        adapter=first_adapter,
    )
    assert run_cli(
        [
            "fetch",
            "--input",
            "https://publisher.example/paper",
            "--output",
            str(output),
        ],
        application=first,
    ) == 0
    first_payload = json.loads(capsys.readouterr().out)
    first.registry.close()
    assert first_adapter.resolve_calls == 1
    assert first_adapter.acquire_calls == 1

    second_adapter = CountingAdapter()
    second = Application.for_test(
        app_root=app_root,
        repository_root=repository,
        adapter=second_adapter,
    )
    assert run_cli(
        ["fetch", "--input", "10.1000/durable-cache", "--output", str(output)],
        application=second,
    ) == 0
    second_payload = json.loads(capsys.readouterr().out)
    assert second_payload == first_payload
    assert second_adapter.resolve_calls == 0
    assert second_adapter.acquire_calls == 0
