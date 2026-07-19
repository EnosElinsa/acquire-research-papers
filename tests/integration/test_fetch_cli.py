import json
from pathlib import Path

from acquire_research_papers.acquisition.adapters.acl import AclAnthologyAdapter
from acquire_research_papers.cli import Application, run_cli


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
