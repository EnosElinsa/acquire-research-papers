from __future__ import annotations

import atexit
import collections
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol
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
# One navigation, PDF request, or citation request; user login waits use timeout_seconds.
DEFAULT_STEP_TIMEOUT_SECONDS = 120
SESSION_CLOSE_SECONDS = 20


def reuse_browser_enabled() -> bool:
    """Production bridges keep one browser per process; ARP_IEEE_REUSE_BROWSER=0 opts out."""
    return os.environ.get("ARP_IEEE_REUSE_BROWSER", "1").strip() != "0"


def browser_platform_supported() -> bool:
    """The pinned Playwright installer and the tested browser flow are Windows-only."""
    return os.name == "nt"


class IeeeBridgeError(RuntimeError):
    def __init__(self, phase: str, message: str) -> None:
        super().__init__(message)
        self.phase = phase


class IeeeTransientError(NetworkTransient):
    """One browser step timed out or IEEE asked the browser to slow down (classified as
    ``network_transient``); the phase names the step."""

    def __init__(self, phase: str, message: str) -> None:
        super().__init__(message)
        self.phase = phase


# Unexpected browser failures, such as a Playwright TimeoutError, that one more attempt in the
# same browser usually clears. Login and access phases are never repeated automatically.
RETRIED_AUTOMATION_PHASES = frozenset({"automation"})
RETRY_DELAY_SECONDS = 5.0


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


def _relay_progress(line: str) -> None:
    """Forward only the fact that the user must act; never the browser's message text."""
    try:
        event = json.loads(line)
        if event.get("status") == "requires_user_action":
            print(json.dumps({"status": "requires_user_action",
                              "phase": event.get("phase", "institution-login"),
                              "message": "Complete login in the dedicated browser."}),
                  file=sys.stderr, flush=True)
    except (ValueError, AttributeError):
        pass


class _BridgeSession:
    """A long-lived browser process answering one JSON line per paper request."""

    def __init__(self, command: list[str], credential_line: str | None) -> None:
        self.process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self._responses: queue.Queue[str | None] = queue.Queue()
        self._errors: collections.deque[str] = collections.deque(maxlen=50)
        threading.Thread(target=self._read_stdout, daemon=True).start()
        self._stderr_reader = threading.Thread(target=self._read_stderr, daemon=True)
        self._stderr_reader.start()
        if credential_line is not None:
            self._write(credential_line)

    def _read_stdout(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            if line.strip():
                self._responses.put(line)
        self._responses.put(None)

    def _read_stderr(self) -> None:
        assert self.process.stderr is not None
        for line in self.process.stderr:
            self._errors.append(line)
            _relay_progress(line)

    def _write(self, line: str) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(line)
        self.process.stdin.flush()

    def alive(self) -> bool:
        return self.process.poll() is None

    def stderr_text(self) -> str:
        self._stderr_reader.join(timeout=5)
        return "".join(self._errors)

    def request(self, payload: dict, *, timeout: float) -> str | None:
        self._write(json.dumps(payload) + "\n")
        try:
            return self._responses.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError("IEEE browser session did not answer in time") from None

    def close(self) -> None:
        # Closing stdin ends the request loop; the browser then flushes its profile.
        try:
            if self.process.stdin is not None:
                self.process.stdin.close()
        except OSError:
            pass
        try:
            self.process.wait(timeout=SESSION_CLOSE_SECONDS)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        for stream in (self.process.stdout, self.process.stderr):
            try:
                if stream:
                    stream.close()
            except OSError:
                pass


class IeeeBridge:
    # The browser enforces its own deadlines first; this is the last-resort process bound.
    process_grace_seconds = 30

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
        credential_provider: Callable[[str], dict | None] | None = None,
        credential_host: str = "",
        data_root: Path | None = None,
        step_timeout_seconds: int = DEFAULT_STEP_TIMEOUT_SECONDS,
        reuse_browser: bool = False,
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
        self.credential_provider = credential_provider
        self.credential_host = credential_host
        self.data_root = data_root.resolve() if data_root else None
        self.step_timeout_seconds = max(1, min(step_timeout_seconds, timeout_seconds))
        # One dedicated browser serves every paper of this process when enabled.
        self.reuse_browser = reuse_browser
        self._session: _BridgeSession | None = None
        self._close_registered = False

    def command(self, reference: str | None, *, run_dir: Path) -> list[str]:
        command = [self.node_path, str(self.script)]
        if reference is not None:
            command.extend(["--reference", reference])
        command.extend([
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
            "--step-timeout-ms",
            str(self.step_timeout_seconds * 1000),
        ])
        command.extend(
            ["--accept-attribute-release", str(self.accept_attribute_release).lower()]
        )
        if self.access_profile:
            command.extend(["--access-profile", str(self.access_profile)])
        if self.data_root:
            command.extend(["--data-root", str(self.data_root)])
        if self.credential_provider:
            command.extend(["--credential-stdin", "true"])
        return command

    def _credential_line(self) -> str | None:
        if not self.credential_provider:
            return None
        # Carry the selected backend's missing state explicitly. The browser
        # may inspect, download, or reuse a session without needing an account.
        credential = self.credential_provider(self.credential_host) or {
            "username": None, "password": None,
        }
        return json.dumps({"host": self.credential_host, **credential}) + "\n"

    def _execute(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        payload = self._credential_line()
        if self.access_profile is None:
            return subprocess.run(command, input=payload, check=False, capture_output=True,
                                  text=True, encoding="utf-8", errors="replace",
                                  timeout=self.timeout_seconds + self.process_grace_seconds,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   stdin=subprocess.PIPE if payload is not None else subprocess.DEVNULL,
                                   text=True, encoding="utf-8", errors="replace",
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        errors: list[str] = []

        def consume_progress() -> None:
            assert process.stderr is not None
            for line in process.stderr:
                errors.append(line)
                _relay_progress(line)

        reader = threading.Thread(target=consume_progress, daemon=True)
        reader.start()
        if payload is not None:
            assert process.stdin is not None
            process.stdin.write(payload)
            process.stdin.close()
            payload = None
        expired = threading.Event()

        def stop() -> None:
            expired.set()
            process.kill()

        timer = threading.Timer(self.timeout_seconds + self.process_grace_seconds, stop)
        timer.daemon = True
        timer.start()
        try:
            assert process.stdout is not None
            output = process.stdout.read()
            process.wait()
            reader.join(timeout=5)
            if expired.is_set():
                raise subprocess.TimeoutExpired(command, self.timeout_seconds + self.process_grace_seconds)
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
        if not browser_platform_supported():
            # On other systems the paper is a manual download, not a local configuration problem.
            raise IeeeBridgeError(
                "unsupported-platform",
                "IEEE browser automation runs only on Windows; download this paper from its "
                "IEEE Xplore page and import it with manual-fetch",
            )
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
                *(["-DataRoot", str(self.data_root)] if self.data_root else []),
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
            if not isinstance(payload, dict):
                continue
            phase = str(payload.get("phase") or "automation")
            message = str(payload.get("message") or "IEEE browser automation failed")
            raw_details = payload.get("details")
            details = raw_details if isinstance(raw_details, dict) else {}
            error_name = str(details.get("errorName") or "")
            if error_name.isidentifier() and len(error_name) <= 40:
                message = f"{message} ({error_name})"
            if phase in {
                "pdf-request-timeout",
                "citation-request-timeout",
                "paper-http-418",
            } or details.get("retryable") is True:
                return IeeeTransientError(phase, f"{message} (IEEE phase: {phase})")
            return IeeeBridgeError(phase, message)
        return IeeeBridgeError("automation", "IEEE browser automation failed")

    def _session_command(self) -> list[str]:
        session_dir = self.work_root / f"ieee-session-{uuid.uuid4().hex}"
        session_dir.mkdir(parents=True, exist_ok=False)
        return [*self.command(None, run_dir=session_dir), "--session", "true"]

    def close(self) -> None:
        """Close a reused browser so its profile is flushed and its lock released."""
        session, self._session = self._session, None
        if session is not None:
            session.close()

    def _session_payload(self, reference: str, run_dir: Path) -> dict:
        session = self._session
        if session is None or not session.alive():
            if session is not None:
                session.close()
            session = _BridgeSession(self._session_command(), self._credential_line())
            self._session = session
            if not self._close_registered:
                atexit.register(self.close)
                self._close_registered = True
        try:
            line = session.request({"reference": reference, "workDir": str(run_dir)},
                                   timeout=self.timeout_seconds + self.process_grace_seconds)
        except TimeoutError:
            self.close()
            raise NetworkTransient("IEEE browser automation timed out.") from None
        except OSError:
            line = None
        if line is None:
            # The browser process ended; its last stderr line explains why.
            errors = session.stderr_text()
            self.close()
            raise self._failure(errors)
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            self.close()
            raise IeeeBridgeError("automation-output", "IEEE bridge returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise IeeeBridgeError("automation-output", "IEEE bridge returned invalid JSON")
        if payload.get("status") == "error":
            if not session.alive():
                self.close()
            raise self._failure(line)
        return payload

    def retrieve(self, reference: str) -> IeeeBridgeResult:
        self._ensure_dependency()
        run_dir = self.work_root / f"ieee-{uuid.uuid4().hex}"
        run_dir.mkdir(parents=True, exist_ok=False)
        if self.reuse_browser:
            payload = self._session_payload(reference, run_dir)
        else:
            payload = self._one_shot_payload(reference, run_dir)
        return self._result(payload, run_dir)

    def _one_shot_payload(self, reference: str, run_dir: Path) -> dict:
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
        if not isinstance(payload, dict):
            raise IeeeBridgeError("automation-output", "IEEE bridge returned invalid JSON")
        return payload

    def _result(self, payload: dict, run_dir: Path) -> IeeeBridgeResult:
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

    def __init__(
        self,
        bridge: IeeeBridgeProtocol,
        *,
        retries: int = 1,
        retry_delay_seconds: float = RETRY_DELAY_SECONDS,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.bridge = bridge
        self.retries = max(0, retries)
        self.retry_delay_seconds = max(0.0, retry_delay_seconds)
        self._sleeper = sleeper
        self._pairs: dict[str, AcquiredPair] = {}

    @staticmethod
    def _retry_reason(error: Exception) -> dict[str, str] | None:
        if isinstance(error, IeeeTransientError):
            return {"error_code": "network_transient", "phase": error.phase}
        if isinstance(error, IeeeBridgeError) and error.phase in RETRIED_AUTOMATION_PHASES:
            return {"error_code": "automation_error", "phase": error.phase}
        return None

    def _retrieve(self, reference: str) -> tuple[IeeeBridgeResult, tuple[dict[str, Any], ...]]:
        """Retrieve once more after a timed-out step or an unexpected browser failure."""
        retried: list[dict[str, Any]] = []
        while True:
            try:
                return self.bridge.retrieve(reference), tuple(retried)
            except (IeeeTransientError, IeeeBridgeError) as error:
                reason = self._retry_reason(error)
                if reason is None or len(retried) >= self.retries:
                    raise
                retried.append({"attempt": len(retried) + 1, **reason})
                print(json.dumps({"event": "ieee_retry", **retried[-1],
                                  "delay_seconds": self.retry_delay_seconds}),
                      file=sys.stderr, flush=True)
                self._sleeper(self.retry_delay_seconds)

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

    def _pair(self, result: IeeeBridgeResult,
              retries: tuple[dict[str, Any], ...] = ()) -> AcquiredPair:
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
            retries=retries,
        )

    def resolve(self, landing_url: str) -> SourceDocument:
        if not self.supports(landing_url):
            raise PageContractChanged("IEEE input is not an exact ieeexplore.ieee.org URL")
        pair = self._pair(*self._retrieve(landing_url))
        self._pairs[pair.document.metadata.landing_url] = pair
        return pair.document

    def acquire(self, document: SourceDocument) -> AcquiredPair:
        pair = self._pairs.get(document.metadata.landing_url)
        if pair is None:
            pair = self._pair(*self._retrieve(document.metadata.landing_url))
            self._pairs[document.metadata.landing_url] = pair
        return pair
