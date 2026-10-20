from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from acquire_research_papers.acquisition.base import (
    AcquiredPair,
    NotOfficial,
    PageContractChanged,
    SourceDocument,
)
from acquire_research_papers.artifacts import validate_pdf
from acquire_research_papers.bibliography import BibMissing
from acquire_research_papers.http import NetworkTransient
from acquire_research_papers.models import PaperMetadata


IEEE_HOST = "ieeexplore.ieee.org"
PLAYWRIGHT_VERSION = "1.61.1"


class IeeeBridgeError(RuntimeError):
    def __init__(self, phase: str, message: str) -> None:
        super().__init__(message)
        self.phase = phase


@dataclass(frozen=True)
class IeeeBridgeResult:
    title: str
    authors: tuple[str, ...]
    year: int
    venue: str
    doi: str
    landing_url: str
    pdf_url: str
    bibtex_url: str
    pdf_bytes: bytes
    bibtex: str
    access: str = "unknown"


class IeeeBridgeProtocol(Protocol):
    def retrieve(self, reference: str) -> IeeeBridgeResult: ...


class IeeeBridge:
    def __init__(
        self,
        *,
        script: Path,
        profile_root: Path,
        dependency_root: Path,
        work_root: Path,
        secret_path: Path,
        node_path: str | None = None,
        installer: Path | None = None,
        timeout_seconds: int = 900,
        accept_attribute_release: bool = True,
        access_profile: Path | None = None,
    ) -> None:
        self.script = script.resolve()
        self.profile_root = profile_root.resolve()
        self.dependency_root = dependency_root.resolve()
        self.work_root = work_root.resolve()
        self.secret_path = secret_path.resolve()
        self.node_path = node_path or shutil.which("node") or "node"
        self.installer = (installer or self.script.parent / "install-playwright.ps1").resolve()
        self.timeout_seconds = timeout_seconds
        self.accept_attribute_release = accept_attribute_release
        self.access_profile = access_profile.resolve() if access_profile else None

    def command(self, reference: str, *, run_dir: Path) -> list[str]:
        command = [
            self.node_path,
            str(self.script),
            "--reference",
            reference,
            "--work-dir",
            str(run_dir.resolve()),
            "--profile-dir",
            str(self.profile_root),
            "--dependency-root",
            str(self.dependency_root),
            "--secret-path",
            str(self.secret_path),
            "--timeout-ms",
            str(self.timeout_seconds * 1000),
        ]
        command.extend(
            ["--accept-attribute-release", str(self.accept_attribute_release).lower()]
        )
        if self.access_profile:
            command.extend(["--access-profile", str(self.access_profile)])
        return command

    def _execute(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        if self.access_profile is None:
            return subprocess.run(command, check=False, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace",
                                  timeout=self.timeout_seconds + 30,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8", errors="replace",
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        errors: list[str] = []

        def consume_progress() -> None:
            assert process.stderr is not None
            for line in process.stderr:
                errors.append(line)
                try:
                    event = json.loads(line)
                    if event.get("status") == "requires_user_action":
                        print(json.dumps({"status": "requires_user_action",
                                          "phase": event.get("phase", "institution-login"),
                                          "message": "Complete login in the dedicated browser."}),
                              file=sys.stderr, flush=True)
                except (ValueError, AttributeError):
                    pass

        reader = threading.Thread(target=consume_progress, daemon=True)
        reader.start()
        expired = threading.Event()

        def stop() -> None:
            expired.set()
            process.kill()

        timer = threading.Timer(self.timeout_seconds + 30, stop)
        timer.daemon = True
        timer.start()
        try:
            assert process.stdout is not None
            output = process.stdout.read()
            process.wait()
            reader.join(timeout=5)
            if expired.is_set():
                raise subprocess.TimeoutExpired(command, self.timeout_seconds + 30)
            return subprocess.CompletedProcess(command, process.returncode, output, "".join(errors))
        finally:
            timer.cancel()
            if process.poll() is None:
                process.kill()
            process.wait()
            for stream in (process.stdout, process.stderr):
                if stream:
                    stream.close()

    def operate(self, operation: str, reference: str | None = None) -> dict:
        if operation not in {"inspect", "login"}:
            raise ValueError("unsupported institution operation")
        self._ensure_dependency()
        run_dir = self.work_root / f"ieee-{uuid.uuid4().hex}"
        run_dir.mkdir(parents=True, exist_ok=False)
        command = self.command(reference or "https://ieeexplore.ieee.org/", run_dir=run_dir)
        if reference is None:
            del command[command.index("--reference"):command.index("--reference") + 2]
        command.extend(["--operation", operation])
        try:
            result = self._execute(command)
        except subprocess.TimeoutExpired:
            raise IeeeBridgeError("assisted-login-timeout", "Institution login timed out; retry login.") from None
        if result.returncode:
            raise self._failure(result.stderr)
        try:
            return json.loads(result.stdout)
        except ValueError:
            raise IeeeBridgeError("automation-output", "IEEE bridge returned invalid diagnostics") from None

    def _dependency_ready(self) -> bool:
        package_path = self.dependency_root / "node_modules" / "playwright-core" / "package.json"
        try:
            package = json.loads(package_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return False
        return package.get("version") == PLAYWRIGHT_VERSION

    def _ensure_dependency(self) -> None:
        if self._dependency_ready():
            return
        process = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self.installer),
                "-DependencyRoot",
                str(self.dependency_root),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.timeout_seconds,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if process.returncode != 0 or not self._dependency_ready():
            raise IeeeBridgeError("dependency-install", "integrity-pinned Playwright installation failed")

    @staticmethod
    def _failure(stderr: str) -> RuntimeError:
        for line in reversed(stderr.splitlines()):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            phase = str(payload.get("phase") or "automation")
            message = str(payload.get("message") or "IEEE browser automation failed")
            if phase in {
                "pdf-request-timeout",
                "citation-request-timeout",
                "paper-http-418",
            }:
                return NetworkTransient(message)
            return IeeeBridgeError(phase, message)
        return IeeeBridgeError("automation", "IEEE browser automation failed")

    def retrieve(self, reference: str) -> IeeeBridgeResult:
        self._ensure_dependency()
        run_dir = self.work_root / f"ieee-{uuid.uuid4().hex}"
        run_dir.mkdir(parents=True, exist_ok=False)
        try:
            process = self._execute(self.command(reference, run_dir=run_dir))
        except subprocess.TimeoutExpired as exc:
            raise NetworkTransient("IEEE browser automation timed out.") from exc
        if process.returncode != 0:
            raise self._failure(process.stderr)
        lines = [line for line in process.stdout.splitlines() if line.strip()]
        if len(lines) != 1:
            raise IeeeBridgeError("automation-output", "IEEE bridge did not emit exactly one JSON object")
        try:
            payload = json.loads(lines[0])
        except json.JSONDecodeError as exc:
            raise IeeeBridgeError("automation-output", "IEEE bridge returned invalid JSON") from exc
        if payload.get("status") != "downloaded":
            raise IeeeBridgeError("automation-output", "IEEE bridge did not report a completed download")
        pdf_path = Path(str(payload.get("pdfPath", ""))).resolve()
        if run_dir.resolve() not in pdf_path.parents:
            raise IeeeBridgeError("path-boundary", "IEEE bridge returned a PDF outside its run directory")
        validate_pdf(pdf_path)
        try:
            authors = tuple(str(value).strip() for value in payload["authors"] if str(value).strip())
            result = IeeeBridgeResult(
                title=str(payload["title"]).strip(),
                authors=authors,
                year=int(payload["year"]),
                venue=str(payload["venue"]).strip(),
                doi=str(payload.get("doi", "")).strip(),
                landing_url=str(payload["landingUrl"]),
                pdf_url=str(payload["pdfUrl"]),
                bibtex_url=str(payload["bibtexUrl"]),
                pdf_bytes=pdf_path.read_bytes(),
                bibtex=str(payload["bibtex"]),
                access=str(payload.get("access", "unknown")),
            )
        except (KeyError, TypeError, ValueError, OSError) as exc:
            raise IeeeBridgeError("automation-output", "IEEE bridge result is incomplete") from exc
        if not result.title or not result.authors or not result.venue:
            raise IeeeBridgeError("automation-output", "IEEE bridge metadata is incomplete")
        return result


class IeeeXploreAdapter:
    name = "ieee-xplore"
    production_hosts = frozenset({IEEE_HOST})

    def __init__(self, bridge: IeeeBridgeProtocol) -> None:
        self.bridge = bridge
        self._pairs: dict[str, AcquiredPair] = {}

    def supports(self, landing_url: str) -> bool:
        parsed = urlsplit(landing_url)
        return bool(
            parsed.scheme == "https"
            and parsed.hostname
            and parsed.hostname.casefold() == IEEE_HOST
        )

    @staticmethod
    def _require_ieee_url(value: str, label: str) -> None:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.hostname.casefold() != IEEE_HOST:
            raise NotOfficial(f"IEEE {label} URL is outside the exact publisher host")

    def _pair(self, result: IeeeBridgeResult) -> AcquiredPair:
        if not result.bibtex.strip():
            raise BibMissing("IEEE official BibTeX export is empty")
        self._require_ieee_url(result.landing_url, "landing")
        self._require_ieee_url(result.pdf_url, "PDF")
        self._require_ieee_url(result.bibtex_url, "BibTeX")
        metadata = PaperMetadata(
            title=result.title,
            authors=result.authors,
            year=result.year,
            venue=result.venue,
            doi=result.doi or None,
            publisher="IEEE",
            landing_url=result.landing_url,
            publication_type="research-article",
        )
        document = SourceDocument(
            metadata=metadata,
            pdf_url=result.pdf_url,
            bibtex_url=result.bibtex_url,
            allowed_hosts=frozenset({IEEE_HOST}),
        )
        return AcquiredPair(
            document=document,
            pdf_bytes=result.pdf_bytes,
            bibtex_text=result.bibtex,
            bibtex_bytes=result.bibtex.encode("utf-8"),
            bibtex_source="publisher_export_api",
        )

    def resolve(self, landing_url: str) -> SourceDocument:
        if not self.supports(landing_url):
            raise PageContractChanged("IEEE input is not an exact ieeexplore.ieee.org URL")
        pair = self._pair(self.bridge.retrieve(landing_url))
        self._pairs[pair.document.metadata.landing_url] = pair
        return pair.document

    def acquire(self, document: SourceDocument) -> AcquiredPair:
        pair = self._pairs.get(document.metadata.landing_url)
        if pair is None:
            pair = self._pair(self.bridge.retrieve(document.metadata.landing_url))
            self._pairs[document.metadata.landing_url] = pair
        return pair
