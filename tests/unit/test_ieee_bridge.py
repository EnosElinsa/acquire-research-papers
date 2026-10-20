import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from acquire_research_papers.acquisition.adapters.ieee import (
    IeeeBridge,
    IeeeBridgeResult,
    IeeeXploreAdapter,
)
from acquire_research_papers.bibliography import BibMissing
from acquire_research_papers.cli import build_parser
from acquire_research_papers.http import NetworkTransient


def bridge_result(*, bibtex: str | None = None) -> IeeeBridgeResult:
    return IeeeBridgeResult(
        title="A Synthetic IEEE Paper",
        authors=("Ada Lovelace", "Alan Turing"),
        year=2026,
        venue="IEEE Transactions on Testing",
        doi="10.1109/test.1",
        landing_url="https://ieeexplore.ieee.org/document/1",
        pdf_url="https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?arnumber=1",
        bibtex_url="https://ieeexplore.ieee.org/xpl/downloadCitations",
        pdf_bytes=b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n",
        bibtex=(
            bibtex
            if bibtex is not None
            else "@article{k,title={A Synthetic IEEE Paper},"
            "author={Lovelace, Ada and Turing, Alan},year={2026},"
            "journal={IEEE Transactions on Testing},doi={10.1109/test.1}}"
        ),
    )


def test_ieee_bridge_uses_dedicated_runtime_paths(tmp_path: Path) -> None:
    bridge = IeeeBridge(
        script=tmp_path / "ieee-playwright.mjs",
        profile_root=tmp_path / "profiles" / "ieee",
        dependency_root=tmp_path / "deps",
        work_root=tmp_path / "runs",
        secret_path=tmp_path / "secrets" / "secrets.clixml",
        node_path="node",
    )
    command = bridge.command(
        "https://ieeexplore.ieee.org/document/11014597",
        run_dir=tmp_path / "runs" / "run-1",
    )
    rendered = " ".join(str(value) for value in command)
    assert "Google\\Chrome\\User Data" not in rendered
    assert str(tmp_path / "profiles" / "ieee") in command
    assert str(tmp_path / "deps") in command
    assert "--secret-path" in command
    assert command[-2:] == ["--accept-attribute-release", "true"]

    manual_bridge = IeeeBridge(
        script=tmp_path / "ieee-playwright.mjs",
        profile_root=tmp_path / "profiles" / "ieee",
        dependency_root=tmp_path / "deps",
        work_root=tmp_path / "runs",
        secret_path=tmp_path / "secrets" / "secrets.clixml",
        node_path="node",
        accept_attribute_release=False,
    )
    manual_command = manual_bridge.command(
        "https://ieeexplore.ieee.org/document/11014597",
        run_dir=tmp_path / "runs" / "run-2",
    )
    assert manual_command[-2:] == ["--accept-attribute-release", "false"]


def test_ieee_bridge_allows_slow_pdf_downloads_by_default(tmp_path: Path) -> None:
    bridge = IeeeBridge(
        script=tmp_path / "ieee-playwright.mjs",
        profile_root=tmp_path / "profiles" / "ieee",
        dependency_root=tmp_path / "deps",
        work_root=tmp_path / "runs",
        secret_path=tmp_path / "secrets" / "secrets.clixml",
        node_path="node",
    )

    command = bridge.command(
        "https://ieeexplore.ieee.org/document/11014597",
        run_dir=tmp_path / "runs" / "run-slow-pdf",
    )

    timeout_index = command.index("--timeout-ms")
    assert command[timeout_index + 1] == "900000"


def test_ieee_bridge_classifies_child_timeout_as_network_transient(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bridge = IeeeBridge(
        script=tmp_path / "ieee-playwright.mjs",
        profile_root=tmp_path / "profiles" / "ieee",
        dependency_root=tmp_path / "deps",
        work_root=tmp_path / "runs",
        secret_path=tmp_path / "secrets" / "secrets.clixml",
        node_path="node",
    )
    monkeypatch.setattr(bridge, "_ensure_dependency", lambda: None)

    def time_out(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], timeout=210)

    monkeypatch.setattr(subprocess, "run", time_out)

    with pytest.raises(NetworkTransient, match="timed out"):
        bridge.retrieve("https://ieeexplore.ieee.org/document/1")


def test_ieee_bridge_classifies_publisher_request_timeout_as_network_transient() -> None:
    error = IeeeBridge._failure(
        '{"status":"error","phase":"pdf-request-timeout",'
        '"message":"IEEE PDF request timed out."}'
    )

    assert isinstance(error, NetworkTransient)


def test_ieee_bridge_classifies_unable_to_load_418_as_network_transient() -> None:
    error = IeeeBridge._failure(
        '{"status":"error","phase":"paper-http-418",'
        '"message":"IEEE Xplore returned a temporary unable-to-load page (418)."}'
    )

    assert isinstance(error, NetworkTransient)


def test_login_without_reference_does_not_claim_a_paper_was_verified(tmp_path, monkeypatch):
    import json
    bridge = IeeeBridge(script=tmp_path/'bridge.mjs', profile_root=tmp_path/'profiles',
        dependency_root=tmp_path/'deps', work_root=tmp_path/'runs', secret_path=tmp_path/'secrets',
        access_profile=tmp_path/'campus.json')
    monkeypatch.setattr(bridge, '_ensure_dependency', lambda: None)
    def execute(command):
        assert '--reference' not in command
        assert command[-2:] == ['--operation', 'login']
        return subprocess.CompletedProcess(command, 0, json.dumps({
            'status':'returned_to_ieee', 'download_verified':False}), '')
    monkeypatch.setattr(bridge, '_execute', execute)
    assert bridge.operate('login')['download_verified'] is False


def test_named_bridge_streams_only_safe_user_action_progress(tmp_path, monkeypatch, capsys):
    import sys
    bridge = IeeeBridge(script=tmp_path/'bridge.mjs', profile_root=tmp_path/'profiles',
        dependency_root=tmp_path/'deps', work_root=tmp_path/'runs', secret_path=tmp_path/'secrets',
        access_profile=tmp_path/'campus.json')
    command = [sys.executable, '-c',
        'import sys; print(\'{"status":"requires_user_action","message":"private signed query"}\', file=sys.stderr); print("{}")']
    result = bridge._execute(command)
    assert result.returncode == 0
    output = capsys.readouterr().err
    assert 'requires_user_action' in output
    assert 'private signed query' not in output


@pytest.mark.parametrize("named_profile", [False, True])
def test_inspection_sends_missing_credentials_over_stdin_instead_of_failing(
    tmp_path, monkeypatch, named_profile
):
    script = tmp_path / "inspect_probe.py"
    script.write_text(
        "import json, sys\n"
        "payload = json.load(sys.stdin)\n"
        "payload['status'] = 'inspected'\n"
        "payload['operation'] = sys.argv[sys.argv.index('--operation') + 1]\n"
        "payload['stdin_mode'] = '--credential-stdin' in sys.argv\n"
        "print(json.dumps(payload))\n",
        encoding="utf-8",
    )
    bridge = IeeeBridge(
        script=script, node_path=sys.executable, profile_root=tmp_path / "profiles",
        dependency_root=tmp_path / "deps", work_root=tmp_path / "runs",
        secret_path=tmp_path / "secrets", credential_provider=lambda host: None,
        credential_host="login.example.edu",
        access_profile=tmp_path / "campus.json" if named_profile else None,
    )
    monkeypatch.setattr(bridge, "_ensure_dependency", lambda: None)

    assert bridge.operate("inspect") == {
        "status": "inspected", "operation": "inspect", "stdin_mode": True,
        "host": "login.example.edu", "username": None, "password": None,
    }


@pytest.mark.skipif(os.name != "nt", reason="DPAPI credential bridge requires Windows")
def test_optional_dpapi_account_read_preserves_denial_and_corruption_errors(tmp_path):
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    prepare = tmp_path / "prepare.ps1"
    prepare.write_text(
        "param([string]$Scripts, [string]$Root)\n"
        "$ErrorActionPreference = 'Stop'\n"
        ". (Join-Path $Scripts 'secret-store.ps1')\n"
        "$empty = New-AcquisitionSecretPayload\n"
        "$empty | Export-Clixml -LiteralPath (Join-Path $Root 'empty.clixml')\n"
        "$secure = [Security.SecureString]::new()\n"
        "foreach ($character in 'synthetic-password'.ToCharArray()) {$secure.AppendChar($character)}\n"
        "$secure.MakeReadOnly()\n"
        "$credential = [Management.Automation.PSCredential]::new('synthetic-user', $secure)\n"
        "Set-IeeeNamedCredential -ProfileId 'campus' -CredentialHost 'login.example.edu' "
        "-Credential $credential -Path (Join-Path $Root 'named.clixml')\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-File", str(prepare), str(scripts), str(tmp_path)],
        capture_output=True, text=True, check=True, timeout=30,
    )
    (tmp_path / "corrupt.clixml").write_text("invalid ciphertext", encoding="utf-8")
    encrypted = (tmp_path / "named.clixml").read_text(encoding="utf-16")
    damaged, replacements = re.subn(
        r'(<SS N="Password">)[^<]+', r'\g<1>invalid-ciphertext', encrypted,
    )
    assert replacements == 1
    (tmp_path / "corrupt-password.clixml").write_text(damaged, encoding="utf-16")
    reader = scripts / "read-browser-credential.ps1"

    def read(filename, *arguments, host="login.example.edu"):
        return subprocess.run(
            ["powershell", "-NoProfile", "-File", str(reader), "-SecretPath",
             str(tmp_path / filename), "-ExpectedHost", host, *arguments],
            capture_output=True, text=True, timeout=30,
        )

    for filename, extra in [
        ("missing.clixml", []), ("missing.clixml", ["-ProfileId", "campus"]),
        ("empty.clixml", []), ("empty.clixml", ["-ProfileId", "campus"]),
        ("named.clixml", ["-ProfileId", "other"]),
    ]:
        result = read(filename, "-Optional", *extra)
        assert result.returncode == 0
        assert json.loads(result.stdout) is None

    configured = read("named.clixml", "-Optional", "-ProfileId", "campus")
    assert configured.returncode == 0
    assert json.loads(configured.stdout) == {
        "username": "synthetic-user", "password": "synthetic-password",
    }
    for filename, extra in [
        ("missing.clixml", []),
        ("corrupt.clixml", ["-Optional"]),
        ("corrupt-password.clixml", ["-Optional", "-ProfileId", "campus"]),
        ("named.clixml", ["-Optional", "-ProfileId", "invalid-profile!"]),
    ]:
        result = read(filename, *extra)
        assert result.returncode != 0
        assert "synthetic-password" not in result.stdout + result.stderr
    denied = read("named.clixml", "-Optional", "-ProfileId", "campus",
                  host="login.example.edu.evil.test")
    assert denied.returncode != 0
    assert "unapproved host" in denied.stderr
    assert "synthetic-password" not in denied.stdout + denied.stderr


def test_ieee_attribute_release_is_automatic_with_an_explicit_opt_out(tmp_path: Path) -> None:
    parser = build_parser()
    ordinary = parser.parse_args(
        ["fetch", "--input", "10.1109/test.1", "--output", str(tmp_path / "ordinary")]
    )
    manual = parser.parse_args(
        [
            "fetch",
            "--input", "10.1109/test.1",
            "--output", str(tmp_path / "manual"),
            "--no-accept-ieee-attribute-release",
        ]
    )
    assert ordinary.accept_ieee_attribute_release is True
    assert manual.accept_ieee_attribute_release is False


class StubBridge:
    def __init__(self, result: IeeeBridgeResult) -> None:
        self.result = result
        self.calls: list[str] = []

    def retrieve(self, reference: str) -> IeeeBridgeResult:
        self.calls.append(reference)
        return self.result


def test_ieee_adapter_returns_one_cached_official_pair() -> None:
    bridge = StubBridge(bridge_result())
    adapter = IeeeXploreAdapter(bridge)
    document = adapter.resolve("https://ieeexplore.ieee.org/document/1")
    pair = adapter.acquire(document)
    assert pair.document.metadata.title == "A Synthetic IEEE Paper"
    assert pair.bibtex_text.startswith("@article")
    assert bridge.calls == ["https://ieeexplore.ieee.org/document/1"]


def test_ieee_adapter_requires_official_bibtex() -> None:
    bridge = StubBridge(bridge_result(bibtex=""))
    with pytest.raises(BibMissing):
        IeeeXploreAdapter(bridge).resolve("https://ieeexplore.ieee.org/document/1")


def test_ieee_adapter_rejects_lookalike_hostname() -> None:
    adapter = IeeeXploreAdapter(StubBridge(bridge_result()))
    assert adapter.supports("https://ieeexplore.ieee.org/document/1")
    assert not adapter.supports("http://ieeexplore.ieee.org/document/1")
    assert not adapter.supports("https://ieeexplore.ieee.org.evil.example/document/1")
