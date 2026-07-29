from __future__ import annotations

import subprocess
import traceback
from pathlib import Path

import pytest

from acquire_research_papers.credentials import (
    API_PROVIDER_HOSTS,
    ApiKeyLoadError,
    CredentialStatusError,
    DpapiCredentialStatusProvider,
    DpapiApiKeyProvider,
)


def _provider(tmp_path: Path, run, **overrides) -> DpapiApiKeyProvider:
    values = {
        "provider": "openalex",
        "expected_host": "api.openalex.org",
        "script": tmp_path / "read-discovery-api-key.ps1",
        "secret_path": tmp_path / "secrets.clixml",
        "process_runner": run,
    }
    values.update(overrides)
    return DpapiApiKeyProvider(**values)


def test_dpapi_api_key_provider_uses_exact_provider_and_host(tmp_path: Path) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="synthetic-key\n", stderr="")

    provider = _provider(tmp_path, run)

    assert provider.optional() == "synthetic-key"
    command, kwargs = calls[0]
    assert command[command.index("-Provider") + 1] == "openalex"
    assert command[command.index("-ExpectedHost") + 1] == "api.openalex.org"
    assert command[-1] == "-AllowMissing"
    assert "synthetic-key" not in command
    assert kwargs["capture_output"] is True
    assert kwargs["timeout"] == 30


def test_optional_key_returns_none_for_one_empty_stdout(tmp_path: Path) -> None:
    provider = _provider(
        tmp_path,
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, stdout="\n", stderr=""
        ),
    )

    assert provider.optional() is None


def test_required_key_rejects_empty_stdout(tmp_path: Path) -> None:
    provider = _provider(
        tmp_path,
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, stdout="", stderr=""
        ),
    )

    with pytest.raises(ApiKeyLoadError, match="could not be loaded"):
        provider()


@pytest.mark.parametrize(
    "result",
    [
        subprocess.CompletedProcess([], 0, stdout="first\nsecond\n", stderr=""),
        subprocess.CompletedProcess([], 1, stdout="TOPSECRET\n", stderr="token=TOPSECRET"),
    ],
)
def test_bridge_failures_do_not_include_process_output(tmp_path: Path, result) -> None:
    provider = _provider(tmp_path, lambda command, **kwargs: result)

    with pytest.raises(ApiKeyLoadError) as caught:
        provider.optional()
    assert "TOPSECRET" not in str(caught.value)
    assert "token=" not in str(caught.value)


@pytest.mark.parametrize(
    "failure",
    [subprocess.TimeoutExpired([], 30), OSError("TOPSECRET")],
)
def test_bridge_wraps_process_failures_without_secret_text(tmp_path: Path, failure) -> None:
    def run(command, **kwargs):
        raise failure

    provider = _provider(tmp_path, run)
    with pytest.raises(ApiKeyLoadError) as caught:
        provider.optional()
    assert "TOPSECRET" not in str(caught.value)
    assert caught.value.__cause__ is None
    formatted = "".join(
        traceback.format_exception(
            type(caught.value), caught.value, caught.value.__traceback__
        )
    )
    assert "TOPSECRET" not in formatted


def test_provider_host_mapping_is_closed(tmp_path: Path) -> None:
    assert API_PROVIDER_HOSTS == {
        "semantic_scholar": "api.semanticscholar.org",
        "openalex": "api.openalex.org",
        "elsevier": "api.elsevier.com",
    }
    with pytest.raises(ValueError, match="Unsupported"):
        _provider(tmp_path, subprocess.run, provider="unknown")
    with pytest.raises(ValueError, match="host"):
        _provider(tmp_path, subprocess.run, expected_host="api.openalex.org.evil.example")


def test_status_provider_returns_only_closed_capability_booleans(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                '{"ieee":true,"mineru":false,"elsevier":true,'
                '"semantic_scholar":true,"openalex":false}\n'
            ),
            stderr="",
        )

    provider = DpapiCredentialStatusProvider(
        script=tmp_path / "credential-status.ps1",
        secret_path=tmp_path / "secrets.clixml",
        process_runner=run,
    )

    assert provider() == {
        "ieee": True,
        "mineru": False,
        "elsevier": True,
        "semantic_scholar": True,
        "openalex": False,
    }
    assert calls[0][calls[0].index("-SecretPath") + 1].endswith("secrets.clixml")


@pytest.mark.parametrize(
    "stdout",
    [
        '{"ieee":true,"mineru":false}\n',
        (
            '{"ieee":true,"mineru":false,"elsevier":false,'
            '"semantic_scholar":"TOPSECRET","openalex":false}\n'
        ),
        "first\nsecond\n",
    ],
)
def test_status_provider_rejects_malformed_or_secret_shaped_output(
    tmp_path: Path, stdout: str
) -> None:
    provider = DpapiCredentialStatusProvider(
        script=tmp_path / "credential-status.ps1",
        secret_path=tmp_path / "secrets.clixml",
        process_runner=lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, stdout=stdout, stderr="token=TOPSECRET"
        ),
    )

    with pytest.raises(CredentialStatusError) as caught:
        provider()
    assert "TOPSECRET" not in str(caught.value)
    assert "token=" not in str(caught.value)


def test_status_provider_suppresses_process_failure_context(tmp_path: Path) -> None:
    def run(command, **kwargs):
        raise OSError("token=TOPSECRET")

    provider = DpapiCredentialStatusProvider(
        script=tmp_path / "credential-status.ps1",
        secret_path=tmp_path / "secrets.clixml",
        process_runner=run,
    )

    with pytest.raises(CredentialStatusError) as caught:
        provider()
    assert caught.value.__cause__ is None
    formatted = "".join(
        traceback.format_exception(
            type(caught.value), caught.value, caught.value.__traceback__
        )
    )
    assert "TOPSECRET" not in formatted
