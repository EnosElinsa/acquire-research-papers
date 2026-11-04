"""One user session for every paper in an acquisition's manual-download queue.

The user downloads official PDFs and raw BibTeX files in any order. Each new file is checked
against every paper still waiting, and a paper is imported as soon as exactly one verified PDF
and one verified BibTeX identify it. Files that match more than one waiting paper are never
assigned, and distinct valid duplicates leave the paper for an explicit single-paper import.
"""
from __future__ import annotations

import math
import time
import webbrowser
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from acquire_research_papers.acquisition.base import SourceDocument
from acquire_research_papers.acquisition.manual_handoff import (
    FileState,
    ManualDownloadWatcher,
    ManualHandoffSelection,
    ManualSourceChanged,
    bibtex_matches,
    document_from_selection,
    pdf_identity_matches,
    read_pdf_identity_text,
    validate_manual_pair,
)
from acquire_research_papers.artifacts import sha256_file
from acquire_research_papers.bibliography import decode_bibtex_bytes, parse_bibtex
from acquire_research_papers.selection import SelectionRecord


IMPORTED = "imported"
WAITING = "waiting"
AMBIGUOUS = "ambiguous"
# open_all opens at most this many official pages up front; later papers open in turn.
OPEN_ALL_LIMIT = 30
OPEN_ALL_PAUSE_SECONDS = 0.3


@dataclass(frozen=True)
class QueueOutcome:
    selection_id: str
    title: str
    status: str
    message: str = ""


@dataclass
class _Classified:
    state: FileState
    kind: str
    digest: str | None = None
    matches: frozenset[str] = frozenset()


@dataclass
class _Paper:
    record: SelectionRecord
    document: SourceDocument
    status: str = WAITING
    message: str = ""
    seen: set[str] = field(default_factory=set)
    shares_a_file: bool = False


class ManualQueueSession:
    def __init__(
        self,
        records: Iterable[SelectionRecord],
        *,
        deliver: Callable[[SelectionRecord, ManualHandoffSelection], None],
        opener: Callable[[str], bool],
        progress: Callable[[str], None] = lambda _line: None,
        poll_interval: float = 1.0,
        stable_polls: int = 2,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if poll_interval <= 0 or stable_polls < 2:
            raise ValueError("manual download polling settings are invalid")
        self._papers = {
            record.selection_id: _Paper(record, document_from_selection(record))
            for record in records
        }
        self._order = list(self._papers)
        self._deliver = deliver
        self._opener = opener
        self._progress = progress
        self._poll_interval = poll_interval
        self._stable_polls = stable_polls
        self._monotonic = monotonic
        self._sleeper = sleeper
        self._classified: dict[Path, _Classified] = {}
        # Pairs whose final verification failed; retried only after either file changes.
        self._rejected: set[tuple[Path, FileState, Path, FileState]] = set()
        self.interrupted = False

    # Public entry points -------------------------------------------------------------------

    def import_folder(self, root: Path) -> list[QueueOutcome]:
        """Import every paper whose verified pair is already in one folder; never waits."""
        files = ManualDownloadWatcher(root).snapshot().files
        self._match(files)
        for paper in self._waiting():
            paper.message = self._missing_message(paper, "in the folder")
        return self._outcomes()

    def watch(
        self,
        root: Path,
        *,
        timeout_seconds: float,
        open_browser: bool,
        open_all: bool = False,
    ) -> list[QueueOutcome]:
        """Prompt for each waiting paper in turn and import pairs as they arrive.

        With ``open_all``, the official pages of the first ``OPEN_ALL_LIMIT`` waiting papers
        open at once, so the user can download them in any order while the session watches.
        """
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("manual download timeout must be positive")
        watcher = ManualDownloadWatcher(root)
        baseline = watcher.snapshot().files
        observations: dict[Path, tuple[FileState, int]] = {}
        total = len(self._order)
        if baseline:
            self._progress(
                f"Watching {watcher.root} for new downloads; the {len(baseline)} PDF or BibTeX "
                "files already there are ignored (import them with --from)."
            )
        opened = self._open_all(watcher.root) if open_browser and open_all else set()
        try:
            for number, selection_id in enumerate(self._order, start=1):
                paper = self._papers[selection_id]
                if paper.status != WAITING:
                    continue
                self._announce(number, total, paper, watcher.root,
                               open_browser=open_browser and selection_id not in opened)
                deadline = self._monotonic() + timeout_seconds
                while True:
                    self._match(self._stable_changes(watcher, baseline, observations))
                    if paper.status != WAITING or not self._waiting():
                        break
                    remaining = deadline - self._monotonic()
                    if remaining <= 0:
                        self._progress(
                            f"[{number}/{total}] No verified pair yet for "
                            f"\"{paper.record.title}\"; moving on. Files for it that arrive "
                            "later in this session still count."
                        )
                        break
                    self._sleeper(min(self._poll_interval, remaining))
                if not self._waiting():
                    break
        except KeyboardInterrupt:
            # Ctrl+C ends the session; imported papers stay imported and are recorded.
            self.interrupted = True
            self._progress("Session ended by the user.")
        for paper in self._waiting():
            paper.message = self._missing_message(paper, "during this session")
        return self._outcomes()

    # Matching ------------------------------------------------------------------------------

    def _waiting(self) -> list[_Paper]:
        return [self._papers[key] for key in self._order if self._papers[key].status == WAITING]

    def _stable_changes(
        self,
        watcher: ManualDownloadWatcher,
        baseline: dict[Path, FileState],
        observations: dict[Path, tuple[FileState, int]],
    ) -> dict[Path, FileState]:
        changed = {
            path: state
            for path, state in watcher.snapshot().files.items()
            if baseline.get(path) != state
        }
        for path in set(observations) - set(changed):
            observations.pop(path)
        stable: dict[Path, FileState] = {}
        for path, state in changed.items():
            previous = observations.get(path)
            count = previous[1] + 1 if previous and previous[0] == state else 1
            observations[path] = (state, count)
            if count >= self._stable_polls:
                stable[path] = state
        return stable

    def _classify(self, path: Path, state: FileState) -> _Classified:
        cached = self._classified.get(path)
        if cached is not None and cached.state == state:
            return cached
        kind = ManualDownloadWatcher._kind(path) or ""
        waiting = self._waiting()
        matches: set[str] = set()
        digest: str | None = None
        try:
            if kind == "pdf":
                text = read_pdf_identity_text(path)
                matches = {
                    paper.record.selection_id
                    for paper in waiting
                    if pdf_identity_matches(text, paper.document)
                }
            elif kind == "bibtex":
                parsed = parse_bibtex(decode_bibtex_bytes(path.read_bytes())[0])
                for paper in waiting:
                    try:
                        bibtex_matches(parsed, paper.document, allow_next_issue_year=True)
                    except ValueError:
                        continue
                    matches.add(paper.record.selection_id)
            if matches:
                digest = sha256_file(path)
        except (OSError, UnicodeError, ValueError):
            matches = set()
        classified = _Classified(state, kind, digest, frozenset(matches))
        self._classified[path] = classified
        return classified

    def _match(self, files: dict[Path, FileState]) -> None:
        waiting = {paper.record.selection_id for paper in self._waiting()}
        candidates: dict[str, dict[str, dict[str, Path]]] = {
            key: {"pdf": {}, "bibtex": {}} for key in waiting
        }
        for path in sorted(files):
            classified = self._classify(path, files[path])
            if classified.digest is None:
                continue
            owners = classified.matches & waiting
            for key in owners:
                self._papers[key].seen.add(classified.kind)
                self._papers[key].shares_a_file |= len(owners) > 1
            if len(owners) != 1:
                # A file that identifies several waiting papers is never assigned to one.
                continue
            (key,) = owners
            candidates[key][classified.kind].setdefault(classified.digest, path)
        for key in self._order:
            if key not in candidates:
                continue
            paper = self._papers[key]
            pdfs, citations = candidates[key]["pdf"], candidates[key]["bibtex"]
            if len(pdfs) > 1 or len(citations) > 1:
                paper.status = AMBIGUOUS
                paper.message = (
                    "more than one distinct valid PDF or BibTeX matches this paper; import it "
                    "with manual-fetch --key and explicit --pdf and --bibtex"
                )
                self._progress(f"Skipped \"{paper.record.title}\": {paper.message}")
                continue
            if len(pdfs) != 1 or len(citations) != 1:
                continue
            pdf, bibtex = next(iter(pdfs.values())), next(iter(citations.values()))
            attempt = (pdf, files[pdf], bibtex, files[bibtex])
            if attempt in self._rejected:
                continue
            try:
                selection = validate_manual_pair(
                    paper.document, pdf, bibtex, allow_next_issue_year=True
                )
            except ManualSourceChanged:
                for path in (pdf, bibtex):
                    self._classified.pop(path, None)
                continue
            except (OSError, UnicodeError, ValueError):
                self._rejected.add(attempt)
                continue
            self._deliver(paper.record, selection)
            paper.status = IMPORTED
            self._progress(f"Imported \"{paper.record.title}\" from {pdf.name} and {bibtex.name}")

    # Messages ------------------------------------------------------------------------------

    def _announce(
        self,
        number: int,
        total: int,
        paper: _Paper,
        root: Path,
        *,
        open_browser: bool,
    ) -> None:
        url = paper.document.metadata.landing_url
        self._progress(
            f"[{number}/{total}] Download the official PDF and raw BibTeX of "
            f"\"{paper.record.title}\" from {url} into {root}"
        )
        if open_browser and not self._open(url):
            # One unopened page must not end the session for the remaining papers.
            self._progress(f"[{number}/{total}] Could not open a browser; open the page yourself.")

    def _open(self, url: str) -> bool:
        try:
            return bool(self._opener(url))
        except (OSError, webbrowser.Error):
            return False

    def _open_all(self, root: Path) -> set[str]:
        waiting = self._waiting()
        first = waiting[:OPEN_ALL_LIMIT]
        opened: set[str] = set()
        for index, paper in enumerate(first):
            if index:
                self._sleeper(OPEN_ALL_PAUSE_SECONDS)  # let the browser keep up
            if self._open(paper.document.metadata.landing_url):
                opened.add(paper.record.selection_id)
        message = (f"Opened {len(opened)} of {len(waiting)} official pages; download each "
                   f"paper's PDF and BibTeX into {root} in any order.")
        if len(waiting) > len(first):
            message += (f" The other {len(waiting) - len(first)} pages open one at a time as "
                        "their turn comes.")
        if len(opened) < len(first):
            message += " Pages that did not open are tried again when their turn comes."
        self._progress(message)
        return opened

    @staticmethod
    def _missing_message(paper: _Paper, where: str) -> str:
        if paper.shares_a_file:
            return (f"a file found {where} matches more than one paper in the queue; import this "
                    "paper with manual-fetch --key and explicit --pdf and --bibtex")
        if paper.seen == {"pdf"}:
            return f"a matching PDF but no matching raw BibTeX was found {where}"
        if paper.seen == {"bibtex"}:
            return f"a matching raw BibTeX but no matching PDF was found {where}"
        return f"no matching PDF or raw BibTeX was found {where}"

    def _outcomes(self) -> list[QueueOutcome]:
        return [
            QueueOutcome(
                selection_id=key,
                title=self._papers[key].record.title,
                status=self._papers[key].status,
                message=self._papers[key].message,
            )
            for key in self._order
        ]
