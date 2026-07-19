from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from subprocess import CompletedProcess
from typing import Any

from acquire_research_papers.artifacts import atomic_write_bytes, sha256_file, validate_pdf


MINERU_CDN_HOST = "cdn-mineru.openxlab.org.cn"


class MineruExtractionError(RuntimeError):
    """MinerU failed without producing a complete parse."""


class MineruRateLimited(MineruExtractionError):
    """MinerU explicitly rate-limited the request."""


@dataclass(frozen=True)
class MineruResult:
    mode: str
    output_dir: Path
    markdown: Path


def _contains_rate_limit(value: str) -> bool:
    return bool(
        re.search(r"(?i)(\b429\b|rate\s*limit|too many requests|quota|qps|throttl)", value)
    )


def _is_exact_cdn_transport_failure(value: str) -> bool:
    has_host = bool(
        re.search(r"(?i)https://cdn-mineru\.openxlab\.org\.cn(?:[/:?]|$)", value)
    )
    has_archive = bool(
        re.search(
            r"(?i)(download(?:ing)?\s+(?:the\s+)?(?:result\s+)?(?:zip|archive)|"
            r"result\s+(?:zip|archive))",
            value,
        )
    )
    has_transport = bool(
        re.search(r"(?i)(unexpected\s+eof|\beof\b|tls(?:\s+handshake)?|handshake)", value)
    )
    return has_host and has_archive and has_transport


def _is_exact_upload_transport_failure(value: str) -> bool:
    has_host = bool(
        re.search(r"(?i)https://mineru\.oss-cn-shanghai\.aliyuncs\.com(?:[/:?]|$)", value)
    )
    has_upload = bool(re.search(r"(?i)(\bput\b|\bupload(?:ing)?\b)", value))
    has_transport = bool(
        re.search(r"(?i)(unexpected\s+eof|\beof\b|tls(?:\s+handshake)?|handshake)", value)
    )
    return has_host and has_upload and has_transport


def _with_no_proxy(environment: dict[str, str]) -> dict[str, str]:
    result = dict(environment)
    for name in ("NO_PROXY", "no_proxy"):
        entries = [part.strip() for part in result.get(name, "").split(",") if part.strip()]
        if MINERU_CDN_HOST.casefold() not in {entry.casefold() for entry in entries}:
            entries.append(MINERU_CDN_HOST)
        result[name] = ",".join(entries)
    return result


def _sanitize_process_log(value: str, token: str = "") -> str:
    sanitized = value.replace(token, "[REDACTED]") if token else value
    sanitized = re.sub(
        r"(https?://[^\s?\"']+)\?[^\s\"']+",
        r"\1?[REDACTED]",
        sanitized,
    )
    return re.sub(
        r"(?i)\b(ossaccesskeyid|signature|x-oss-security-token|token)=([^&\s]+)",
        r"\1=[REDACTED]",
        sanitized,
    )


def _find_markdown(output_dir: Path) -> Path:
    candidates = sorted(path for path in output_dir.rglob("*.md") if path.is_file())
    if len(candidates) != 1:
        raise MineruExtractionError(
            f"MinerU output must contain exactly one Markdown file; found {len(candidates)}"
        )
    return candidates[0]


class DpapiMineruTokenProvider:
    def __init__(self, *, script: Path, secret_path: Path, timeout_seconds: int = 30) -> None:
        self.script = script.resolve()
        self.secret_path = secret_path.resolve()
        self.timeout_seconds = timeout_seconds

    def __call__(self) -> str:
        process = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self.script),
                "-SecretPath",
                str(self.secret_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.timeout_seconds,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        lines = [line for line in process.stdout.splitlines() if line]
        if process.returncode != 0 or len(lines) != 1:
            raise MineruExtractionError("encrypted MinerU token could not be loaded")
        return lines[0]


class MineruCliRunner:
    def __init__(
        self,
        *,
        token_provider: Callable[[], str],
        executable: str = "mineru-open-api",
        executable_resolver: Callable[[str], str | None] = shutil.which,
        process_runner: Callable[..., CompletedProcess[str]] = subprocess.run,
        timeout_seconds: int = 1800,
    ) -> None:
        self.token_provider = token_provider
        self.executable = executable_resolver(executable) or executable
        self.process_runner = process_runner
        self.timeout_seconds = timeout_seconds

    def _invoke(self, command: list[str], environment: dict[str, str]) -> CompletedProcess[str]:
        try:
            return self.process_runner(
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                env=environment,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as exc:
            raise MineruExtractionError("MinerU CLI timed out") from exc

    @staticmethod
    def _combined(process: CompletedProcess[str], token: str = "") -> str:
        value = f"{process.stdout or ''}\n{process.stderr or ''}"
        return _sanitize_process_log(value, token)

    def __call__(self, pdf: Path, output: Path) -> MineruResult:
        validate_pdf(pdf)
        precision = output / "precision"
        flash = output / "flash"
        precision.mkdir(parents=True, exist_ok=True)
        token = self.token_provider()
        if not token:
            raise MineruExtractionError("MinerU token scope is empty")
        environment = _with_no_proxy(dict(os.environ))
        environment["MINERU_TOKEN"] = token
        command = [
            self.executable,
            "extract",
            str(pdf),
            "-o",
            str(precision),
            "-f",
            "md",
            "--model",
            "pipeline",
            "--language",
            "en",
        ]
        try:
            for attempt in range(2):
                precision_process = self._invoke(command, dict(environment))
                precision_log = self._combined(precision_process, token)
                if _contains_rate_limit(precision_log):
                    raise MineruRateLimited("MinerU rate limit detected; retry later")
                if precision_process.returncode == 0:
                    break
                if attempt == 0 and _is_exact_upload_transport_failure(precision_log):
                    continue
                break
        finally:
            token = ""
            environment.pop("MINERU_TOKEN", None)

        if precision_process.returncode == 0:
            return MineruResult(
                mode="precision",
                output_dir=precision.resolve(),
                markdown=_find_markdown(precision).resolve(),
            )
        if not _is_exact_cdn_transport_failure(precision_log):
            raise MineruExtractionError(
                f"MinerU precision extraction failed: {precision_log.strip()[-500:]}"
            )

        flash.mkdir(parents=True, exist_ok=True)
        flash_command = [
            self.executable,
            "flash-extract",
            str(pdf),
            "-o",
            str(flash),
            "--language",
            "en",
        ]
        flash_process = self._invoke(flash_command, environment)
        flash_log = self._combined(flash_process)
        if _contains_rate_limit(flash_log):
            raise MineruRateLimited("MinerU rate limit detected during flash fallback")
        if flash_process.returncode != 0:
            raise MineruExtractionError(
                f"MinerU flash fallback failed: {flash_log.strip()[-500:]}"
            )
        return MineruResult(
            mode="flash-extract",
            output_dir=flash.resolve(),
            markdown=_find_markdown(flash).resolve(),
        )


class MineruCache:
    def __init__(
        self,
        root: Path,
        *,
        runner: Callable[[Path, Path], MineruResult],
        retention: timedelta = timedelta(days=7),
    ) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.runner = runner
        self.retention = retention

    def key_for(self, pdf: Path) -> str:
        return sha256_file(pdf)

    @staticmethod
    def _metadata_path(entry: Path) -> Path:
        return entry / "metadata.json"

    def _load(self, entry: Path, expected_hash: str) -> tuple[MineruResult, dict[str, Any]] | None:
        metadata_path = self._metadata_path(entry)
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if (
                metadata.get("schema_version") != 1
                or metadata.get("key") != expected_hash
                or metadata.get("pdf_sha256") != expected_hash
            ):
                return None
            output_dir = (entry / metadata["output_dir"]).resolve()
            markdown = (entry / metadata["markdown"]).resolve()
        except (OSError, KeyError, TypeError, json.JSONDecodeError):
            return None
        if entry.resolve() not in output_dir.parents or output_dir not in markdown.parents:
            return None
        if not output_dir.is_dir() or not markdown.is_file():
            return None
        return (
            MineruResult(
                mode=str(metadata["mode"]),
                output_dir=output_dir,
                markdown=markdown,
            ),
            metadata,
        )

    def _write_metadata(self, entry: Path, metadata: dict[str, Any]) -> None:
        atomic_write_bytes(
            self._metadata_path(entry),
            (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )

    def parse(self, pdf: Path) -> MineruResult:
        validate_pdf(pdf)
        key = self.key_for(pdf)
        entry = self.root / key
        entry.mkdir(parents=True, exist_ok=True)
        cached = self._load(entry, key)
        if cached:
            result, metadata = cached
            metadata["last_accessed"] = datetime.now(UTC).isoformat()
            self._write_metadata(entry, metadata)
            return result

        lock = entry / "parse.lock"
        lock_acquired = False
        try:
            with lock.open("x", encoding="utf-8") as handle:
                handle.write(str(os.getpid()))
            lock_acquired = True
            cached = self._load(entry, key)
            if cached:
                result, metadata = cached
                metadata["last_accessed"] = datetime.now(UTC).isoformat()
                self._write_metadata(entry, metadata)
                return result
            result = self.runner(pdf.resolve(), entry)
            output_dir = result.output_dir.resolve()
            markdown = result.markdown.resolve()
            if entry.resolve() not in output_dir.parents or output_dir not in markdown.parents:
                raise MineruExtractionError("MinerU runner returned output outside its cache entry")
            if not markdown.is_file():
                raise MineruExtractionError("MinerU runner did not produce its reported Markdown file")
            now = datetime.now(UTC).isoformat()
            metadata = {
                "schema_version": 1,
                "key": key,
                "pdf_sha256": key,
                "mode": result.mode,
                "output_dir": output_dir.relative_to(entry).as_posix(),
                "markdown": markdown.relative_to(entry).as_posix(),
                "created_at": now,
                "last_accessed": now,
            }
            self._write_metadata(entry, metadata)
            return result
        except FileExistsError as exc:
            raise MineruExtractionError("MinerU cache entry is already being parsed") from exc
        finally:
            if lock_acquired:
                lock.unlink(missing_ok=True)

    def purge_expired(self, *, now: datetime | None = None) -> list[str]:
        current = now or datetime.now(UTC)
        removed: list[str] = []
        for entry in sorted(path for path in self.root.iterdir() if path.is_dir()):
            if (entry / "parse.lock").exists():
                continue
            try:
                metadata = json.loads(self._metadata_path(entry).read_text(encoding="utf-8"))
                last_accessed = datetime.fromisoformat(str(metadata["last_accessed"]))
            except (OSError, KeyError, ValueError, json.JSONDecodeError):
                continue
            if current - last_accessed > self.retention:
                shutil.rmtree(entry)
                removed.append(entry.name)
        return removed

    def export(self, result: MineruResult, destination: Path) -> Path:
        target = destination.resolve()
        if target.exists():
            raise FileExistsError(f"Markdown export destination already exists: {target}")
        shutil.copytree(result.output_dir, target)
        return target
