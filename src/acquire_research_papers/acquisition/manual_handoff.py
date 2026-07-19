from __future__ import annotations

import math
import re
import time
import unicodedata
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from acquire_research_papers.acquisition.base import AcquiredPair, SourceDocument
from acquire_research_papers.acquisition.adapters.elsevier_api import ElsevierSearchRecord
from acquire_research_papers.artifacts import sha256_file, validate_pdf
from acquire_research_papers.bibliography import parse_bibtex, verify_bibliography


class PdfIdentityMismatch(ValueError):
    """A stable PDF does not identify the expected paper."""


class ManualDownloadAmbiguous(RuntimeError):
    """More than one distinct valid manual download could be delivered."""


class ManualDownloadTimeout(TimeoutError):
    """No unique valid PDF and BibTeX pair appeared before the deadline."""


class ManualBrowserOpenError(RuntimeError):
    """The canonical publisher page could not be opened for manual interaction."""


class ManualSourceChanged(RuntimeError):
    """A manual source file changed while its identity was being verified."""


@dataclass(frozen=True)
class FileState:
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class DownloadSnapshot:
    files: dict[Path, FileState]


@dataclass(frozen=True)
class ManualHandoffSelection:
    source_pdf: Path
    source_bibtex: Path
    pair: AcquiredPair


@dataclass(frozen=True)
class ManualHandoffAcquisition:
    record: ElsevierSearchRecord
    selection: ManualHandoffSelection


class ElsevierSearchResolver(Protocol):
    def resolve(self, reference: str) -> ElsevierSearchRecord: ...


_PDF_SUFFIXES = frozenset({".pdf"})
_BIBTEX_SUFFIXES = frozenset({".bib", ".bibtex", ".txt"})
_PARTIAL_SUFFIXES = frozenset({".crdownload", ".part", ".tmp", ".partial", ".download"})


def _normalized_words(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.findall(r"\w+", normalized))


def _compact_doi(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value).casefold())


def _file_state(path: Path) -> FileState:
    stat = path.stat()
    return FileState(stat.st_size, stat.st_mtime_ns)


def validate_pdf_identity(path: Path, document: SourceDocument) -> None:
    candidate = path.resolve()
    validate_pdf(candidate)
    try:
        reader = PdfReader(candidate, strict=False)
        if not reader.pages:
            raise PdfIdentityMismatch("manual PDF has no pages")
        if reader.is_encrypted and reader.decrypt("") == 0:
            raise PdfIdentityMismatch("manual PDF is encrypted and cannot be inspected")
        embedded_title = ""
        if reader.metadata and reader.metadata.title:
            embedded_title = str(reader.metadata.title)
        page_texts = [(page.extract_text() or "") for page in reader.pages[:3]]
    except PdfIdentityMismatch:
        raise
    except (OSError, PdfReadError, ValueError, TypeError) as exc:
        raise PdfIdentityMismatch("manual PDF could not be parsed") from exc

    title_text = "\n".join((embedded_title, page_texts[0]))
    identity_text = "\n".join((embedded_title, *page_texts))
    doi = document.metadata.doi
    expected_title = _normalized_words(document.metadata.title)
    title_matches = bool(expected_title and expected_title in _normalized_words(title_text))
    doi_matches = bool(doi and _compact_doi(doi) in _compact_doi(identity_text))
    if title_matches and (not doi or doi_matches):
        return
    raise PdfIdentityMismatch("manual PDF does not match both the expected title and DOI")


def validate_manual_pair(
    document: SourceDocument,
    pdf_path: Path,
    bibtex_path: Path,
) -> ManualHandoffSelection:
    source_pdf = pdf_path.resolve()
    source_bibtex = bibtex_path.resolve()
    if not source_pdf.is_file() or not source_bibtex.is_file():
        raise FileNotFoundError("manual PDF and BibTeX paths must both be files")
    pdf_before = _file_state(source_pdf)
    bibtex_before = _file_state(source_bibtex)
    validate_pdf_identity(source_pdf, document)
    bibtex_text = source_bibtex.read_bytes().decode("utf-8")
    verify_bibliography(document.metadata, parse_bibtex(bibtex_text))
    pdf_bytes = source_pdf.read_bytes()
    if _file_state(source_pdf) != pdf_before or _file_state(source_bibtex) != bibtex_before:
        raise ManualSourceChanged("manual source changed during identity verification")
    return ManualHandoffSelection(
        source_pdf=source_pdf,
        source_bibtex=source_bibtex,
        pair=AcquiredPair(
            document=document,
            pdf_bytes=pdf_bytes,
            bibtex_text=bibtex_text,
        ),
    )


class ManualDownloadWatcher:
    def __init__(
        self,
        root: Path,
        *,
        poll_interval: float = 1.0,
        stable_polls: int = 2,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.root = root.resolve()
        if not self.root.is_dir():
            raise ValueError("manual download watch path must be an existing directory")
        if poll_interval <= 0 or stable_polls < 2:
            raise ValueError("manual download polling settings are invalid")
        self.poll_interval = poll_interval
        self.stable_polls = stable_polls
        self._monotonic = monotonic
        self._sleeper = sleeper

    @staticmethod
    def _kind(path: Path) -> str | None:
        suffix = path.suffix.casefold()
        if suffix in _PARTIAL_SUFFIXES:
            return None
        if suffix in _PDF_SUFFIXES:
            return "pdf"
        if suffix in _BIBTEX_SUFFIXES:
            return "bibtex"
        return None

    def _scan(self) -> dict[Path, FileState]:
        found: dict[Path, FileState] = {}
        for candidate in self.root.iterdir():
            if self._kind(candidate) is None:
                continue
            try:
                resolved = candidate.resolve()
                if resolved.parent != self.root:
                    continue
                stat = resolved.stat()
            except (FileNotFoundError, OSError, RuntimeError):
                continue
            if stat.st_size <= 0 or not resolved.is_file():
                continue
            found[resolved] = FileState(stat.st_size, stat.st_mtime_ns)
        return found

    def snapshot(self) -> DownloadSnapshot:
        return DownloadSnapshot(files=self._scan())

    def wait_for_pair(
        self,
        document: SourceDocument,
        baseline: DownloadSnapshot,
        *,
        timeout_seconds: float,
    ) -> ManualHandoffSelection:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("manual download timeout must be positive")
        deadline = self._monotonic() + timeout_seconds
        observations: dict[Path, tuple[FileState, int]] = {}
        stable_paths: set[Path] = set()
        validation_cache: dict[Path, tuple[FileState, str | None]] = {}
        stable_counts = {"pdf": 0, "bibtex": 0}

        while True:
            changed = {
                path: state
                for path, state in self._scan().items()
                if baseline.files.get(path) != state
            }
            for path in set(observations) - set(changed):
                observations.pop(path, None)
                stable_paths.discard(path)
                validation_cache.pop(path, None)
            for path, state in changed.items():
                previous = observations.get(path)
                count = previous[1] + 1 if previous and previous[0] == state else 1
                observations[path] = (state, count)
                if count >= self.stable_polls:
                    stable_paths.add(path)
                else:
                    stable_paths.discard(path)

            valid_pdfs: dict[str, Path] = {}
            valid_bibtex: dict[str, Path] = {}
            stable_counts = {"pdf": 0, "bibtex": 0}
            for path in sorted(stable_paths):
                kind = self._kind(path)
                if kind is None:
                    continue
                stable_counts[kind] += 1
                state = changed[path]
                cached_validation = validation_cache.get(path)
                if cached_validation is not None and cached_validation[0] == state:
                    digest = cached_validation[1]
                    if digest is not None:
                        (valid_pdfs if kind == "pdf" else valid_bibtex).setdefault(digest, path)
                    continue
                try:
                    if kind == "pdf":
                        validate_pdf_identity(path, document)
                    else:
                        raw = path.read_text(encoding="utf-8")
                        verify_bibliography(document.metadata, parse_bibtex(raw))
                    digest = sha256_file(path)
                    validation_cache[path] = (state, digest)
                    (valid_pdfs if kind == "pdf" else valid_bibtex).setdefault(digest, path)
                except (OSError, UnicodeError, ValueError):
                    validation_cache[path] = (state, None)
                    continue

            if len(valid_pdfs) > 1 or len(valid_bibtex) > 1:
                raise ManualDownloadAmbiguous(
                    "multiple distinct valid manual downloads match the requested paper"
                )
            if len(valid_pdfs) == 1 and len(valid_bibtex) == 1:
                selected_paths = (
                    next(iter(valid_pdfs.values())),
                    next(iter(valid_bibtex.values())),
                )
                try:
                    return validate_manual_pair(document, *selected_paths)
                except ManualSourceChanged:
                    for path in selected_paths:
                        observations.pop(path, None)
                        stable_paths.discard(path)
                        validation_cache.pop(path, None)
                    continue
            if self._monotonic() >= deadline:
                raise ManualDownloadTimeout(
                    "manual download timed out with "
                    f"stable PDF={stable_counts['pdf']}, BibTeX={stable_counts['bibtex']}"
                )
            self._sleeper(min(self.poll_interval, max(0.0, deadline - self._monotonic())))


class ManualHandoffWorkflow:
    def __init__(
        self,
        *,
        resolver: ElsevierSearchResolver,
        opener: Callable[[str], bool],
        watcher_factory: Callable[[Path], ManualDownloadWatcher] = ManualDownloadWatcher,
    ) -> None:
        self.resolver = resolver
        self.opener = opener
        self.watcher_factory = watcher_factory

    def acquire(
        self,
        reference: str,
        *,
        watch: Path | None = None,
        timeout_seconds: float = 900,
        open_browser: bool = True,
        pdf: Path | None = None,
        bibtex: Path | None = None,
        notifier: Callable[[str, Path], None] | None = None,
    ) -> ManualHandoffAcquisition:
        if (pdf is None) != (bibtex is None):
            raise ValueError("--pdf and --bibtex must be supplied together")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("manual download timeout must be positive")
        record = self.resolver.resolve(reference)
        if pdf is not None and bibtex is not None:
            selection = validate_manual_pair(record.document, pdf, bibtex)
            return ManualHandoffAcquisition(record=record, selection=selection)

        watch_root = (watch or (Path.home() / "Downloads")).resolve()
        watcher = self.watcher_factory(watch_root)
        baseline = watcher.snapshot()
        if notifier is not None:
            notifier(record.document.metadata.landing_url, watch_root)
        if open_browser:
            try:
                opened = self.opener(record.document.metadata.landing_url)
            except (OSError, webbrowser.Error) as exc:
                raise ManualBrowserOpenError(
                    "the canonical ScienceDirect page could not be opened"
                ) from exc
            if not opened:
                raise ManualBrowserOpenError(
                    "the canonical ScienceDirect page could not be opened"
                )
        selection = watcher.wait_for_pair(
            record.document,
            baseline,
            timeout_seconds=timeout_seconds,
        )
        return ManualHandoffAcquisition(record=record, selection=selection)
