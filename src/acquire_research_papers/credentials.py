from __future__ import annotations

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
        try:
            process = self.process_runner(
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ApiKeyLoadError("Encrypted API key could not be loaded.") from exc
        lines = [line.strip() for line in process.stdout.splitlines() if line.strip()]
        if process.returncode != 0 or len(lines) > 1:
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
