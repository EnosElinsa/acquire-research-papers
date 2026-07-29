from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from subprocess import CompletedProcess
from types import MappingProxyType


API_PROVIDER_HOSTS: Mapping[str, str] = MappingProxyType(
    {
        "semantic_scholar": "api.semanticscholar.org",
        "openalex": "api.openalex.org",
        "elsevier": "api.elsevier.com",
    }
)


class ApiKeyLoadError(RuntimeError):
    """Raised when a host-bound API key cannot be loaded from DPAPI storage."""


class CredentialStatusError(RuntimeError):
    """Raised when capability status cannot be read safely."""


CAPABILITY_NAMES = (
    "ieee",
    "mineru",
    "elsevier",
    "semantic_scholar",
    "openalex",
)


def _run_powershell_bridge(
    command: list[str],
    *,
    process_runner: Callable[..., CompletedProcess[str]],
    timeout_seconds: int,
    error_type: type[RuntimeError],
    error_message: str,
) -> list[str]:
    try:
        process = process_runner(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        raise error_type(error_message) from None
    if process.returncode != 0:
        raise error_type(error_message)
    return [line.strip() for line in process.stdout.splitlines() if line.strip()]


class DpapiApiKeyProvider:
    def __init__(
        self,
        *,
        provider: str,
        expected_host: str,
        script: Path,
        secret_path: Path,
        process_runner: Callable[..., CompletedProcess[str]] = subprocess.run,
        timeout_seconds: int = 30,
    ) -> None:
        name = provider.strip().casefold()
        approved_host = API_PROVIDER_HOSTS.get(name)
        if approved_host is None:
            raise ValueError("Unsupported discovery API provider.")
        if expected_host.casefold() != approved_host:
            raise ValueError("Discovery API host does not match the provider.")
        self.provider = name
        self.expected_host = approved_host
        self.script = script.resolve()
        self.secret_path = secret_path.resolve()
        self.process_runner = process_runner
        self.timeout_seconds = timeout_seconds

    def _read(self, *, allow_missing: bool) -> str | None:
        command = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(self.script),
            "-Provider",
            self.provider,
            "-ExpectedHost",
            self.expected_host,
            "-SecretPath",
            str(self.secret_path),
        ]
        if allow_missing:
            command.append("-AllowMissing")
        lines = _run_powershell_bridge(
            command,
            process_runner=self.process_runner,
            timeout_seconds=self.timeout_seconds,
            error_type=ApiKeyLoadError,
            error_message="Encrypted API key could not be loaded.",
        )
        if len(lines) > 1:
            raise ApiKeyLoadError("Encrypted API key could not be loaded.")
        if not lines:
            if allow_missing:
                return None
            raise ApiKeyLoadError("Encrypted API key could not be loaded.")
        return lines[0]

    def __call__(self) -> str:
        value = self._read(allow_missing=False)
        if value is None:
            raise ApiKeyLoadError("Encrypted API key could not be loaded.")
        return value

    def optional(self) -> str | None:
        return self._read(allow_missing=True)


class DpapiCredentialStatusProvider:
    def __init__(
        self,
        *,
        script: Path,
        secret_path: Path,
        process_runner: Callable[..., CompletedProcess[str]] = subprocess.run,
        timeout_seconds: int = 30,
    ) -> None:
        self.script = script.resolve()
        self.secret_path = secret_path.resolve()
        self.process_runner = process_runner
        self.timeout_seconds = timeout_seconds

    def __call__(self) -> dict[str, bool]:
        command = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(self.script),
            "-SecretPath",
            str(self.secret_path),
        ]
        message = "Credential capability status is unavailable."
        lines = _run_powershell_bridge(
            command,
            process_runner=self.process_runner,
            timeout_seconds=self.timeout_seconds,
            error_type=CredentialStatusError,
            error_message=message,
        )
        if len(lines) != 1:
            raise CredentialStatusError("Credential capability status is unavailable.")
        try:
            payload = json.loads(lines[0])
        except (json.JSONDecodeError, TypeError):
            raise CredentialStatusError(message) from None
        if (
            not isinstance(payload, dict)
            or set(payload) != set(CAPABILITY_NAMES)
            or any(type(payload[name]) is not bool for name in CAPABILITY_NAMES)
        ):
            raise CredentialStatusError("Credential capability status is unavailable.")
        return {name: payload[name] for name in CAPABILITY_NAMES}
