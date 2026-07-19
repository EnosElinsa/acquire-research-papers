from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from acquire_research_papers.artifacts import validate_pdf


PLAYWRIGHT_VERSION = "1.61.1"
SCIENCEDIRECT_HOST = "www.sciencedirect.com"
SCIENCEDIRECT_SCAU_PROXY_HOST = "www-sciencedirect-com-s.vpn.scau.edu.cn"


class ScienceDirectBridgeError(RuntimeError):
    def __init__(self, phase: str, message: str) -> None:
        super().__init__(message)
        self.phase = phase


@dataclass(frozen=True)
class ScienceDirectBridgeResult:
    pii: str
    title: str
    authors: tuple[str, ...]
    year: int
    venue: str
    doi: str
    publisher: str
    landing_url: str
    pdf_url: str
    bibtex_url: str
    access_pdf_url: str
    access_bibtex_url: str
    pdf_bytes: bytes
    bibtex: str


class ScienceDirectBridgeProtocol(Protocol):
    def retrieve(self, reference: str) -> ScienceDirectBridgeResult: ...


class ScienceDirectBridge:
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
    ) -> None:
        self.script = script.resolve()
        self.profile_root = profile_root.resolve()
        self.dependency_root = dependency_root.resolve()
        self.work_root = work_root.resolve()
        self.secret_path = secret_path.resolve()
        self.node_path = node_path or shutil.which("node") or "node"
        self.installer = (installer or self.script.parent / "install-playwright.ps1").resolve()
        self.timeout_seconds = timeout_seconds

    def command(self, reference: str, *, run_dir: Path) -> list[str]:
        return [
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
            raise ScienceDirectBridgeError(
                "dependency-install",
                "integrity-pinned Playwright installation failed",
            )

    @staticmethod
    def _failure(stderr: str) -> ScienceDirectBridgeError:
        for line in reversed(stderr.splitlines()):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            phase = str(payload.get("phase") or "automation")
            message = str(payload.get("message") or "ScienceDirect browser automation failed")
            return ScienceDirectBridgeError(phase, message)
        return ScienceDirectBridgeError("automation", "ScienceDirect browser automation failed")

    @staticmethod
    def _require_host(value: str, expected: str, label: str) -> None:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.hostname.casefold() != expected:
            raise ScienceDirectBridgeError(
                "artifact-host",
                f"ScienceDirect bridge returned an invalid {label} host",
            )

    def retrieve(self, reference: str) -> ScienceDirectBridgeResult:
        self._ensure_dependency()
        run_dir = self.work_root / f"sciencedirect-{uuid.uuid4().hex}"
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
            raise ScienceDirectBridgeError(
                "automation-output",
                "ScienceDirect bridge did not emit exactly one JSON object",
            )
        try:
            payload = json.loads(lines[0])
        except json.JSONDecodeError as exc:
            raise ScienceDirectBridgeError(
                "automation-output",
                "ScienceDirect bridge returned invalid JSON",
            ) from exc
        if payload.get("status") != "downloaded":
            raise ScienceDirectBridgeError(
                "automation-output",
                "ScienceDirect bridge did not report a completed download",
            )
        pdf_path = Path(str(payload.get("pdfPath", ""))).resolve()
        if run_dir.resolve() not in pdf_path.parents:
            raise ScienceDirectBridgeError(
                "path-boundary",
                "ScienceDirect bridge returned a PDF outside its run directory",
            )
        validate_pdf(pdf_path)
        try:
            result = ScienceDirectBridgeResult(
                pii=str(payload["pii"]).strip().upper(),
                title=str(payload["title"]).strip(),
                authors=tuple(
                    str(value).strip() for value in payload["authors"] if str(value).strip()
                ),
                year=int(payload["year"]),
                venue=str(payload["venue"]).strip(),
                doi=str(payload["doi"]).strip(),
                publisher=str(payload["publisher"]).strip(),
                landing_url=str(payload["landingUrl"]),
                pdf_url=str(payload["pdfUrl"]),
                bibtex_url=str(payload["bibtexUrl"]),
                access_pdf_url=str(payload["accessPdfUrl"]),
                access_bibtex_url=str(payload["accessBibtexUrl"]),
                pdf_bytes=pdf_path.read_bytes(),
                bibtex=str(payload["bibtex"]),
            )
        except (KeyError, TypeError, ValueError, OSError) as exc:
            raise ScienceDirectBridgeError(
                "automation-output",
                "ScienceDirect bridge result is incomplete",
            ) from exc
        if not result.pii or not result.title or not result.authors or not result.venue:
            raise ScienceDirectBridgeError(
                "automation-output",
                "ScienceDirect bridge metadata is incomplete",
            )
        self._require_host(result.landing_url, SCIENCEDIRECT_HOST, "landing")
        self._require_host(result.pdf_url, SCIENCEDIRECT_HOST, "PDF")
        self._require_host(result.bibtex_url, SCIENCEDIRECT_HOST, "BibTeX")
        self._require_host(
            result.access_pdf_url,
            SCIENCEDIRECT_SCAU_PROXY_HOST,
            "access PDF",
        )
        self._require_host(
            result.access_bibtex_url,
            SCIENCEDIRECT_SCAU_PROXY_HOST,
            "access BibTeX",
        )
        return result
