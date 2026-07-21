from __future__ import annotations

import json
import shutil
import subprocess
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
        timeout_seconds: int = 180,
        accept_attribute_release: bool = False,
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
        if self.accept_attribute_release:
            command.extend(["--accept-attribute-release", "true"])
        return command

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
    def _failure(stderr: str) -> IeeeBridgeError:
        for line in reversed(stderr.splitlines()):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            phase = str(payload.get("phase") or "automation")
            message = str(payload.get("message") or "IEEE browser automation failed")
            return IeeeBridgeError(phase, message)
        return IeeeBridgeError("automation", "IEEE browser automation failed")

    def retrieve(self, reference: str) -> IeeeBridgeResult:
        self._ensure_dependency()
        run_dir = self.work_root / f"ieee-{uuid.uuid4().hex}"
        run_dir.mkdir(parents=True, exist_ok=False)
        process = subprocess.run(
            self.command(reference, run_dir=run_dir),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.timeout_seconds + 30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
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
        hostname = urlsplit(landing_url).hostname
        return bool(hostname and hostname.casefold().rstrip(".") == IEEE_HOST)

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
