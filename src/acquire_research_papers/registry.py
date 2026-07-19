from __future__ import annotations

import re
import sqlite3
import threading
import unicodedata
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from acquire_research_papers.models import ErrorCode, PaperStatus, normalize_doi


class StateTransitionError(ValueError):
    """A paper was asked to skip a required durable state."""


ALLOWED_TRANSITIONS: dict[PaperStatus, set[PaperStatus]] = {
    PaperStatus.DISCOVERED: {
        PaperStatus.AUTO_ACCEPTED,
        PaperStatus.PENDING_REVIEW,
        PaperStatus.REJECTED,
    },
    PaperStatus.AUTO_ACCEPTED: {PaperStatus.RESOLVING},
    PaperStatus.RESOLVING: {PaperStatus.DOWNLOADED},
    PaperStatus.DOWNLOADED: {PaperStatus.PAIR_VERIFIED},
    PaperStatus.PAIR_VERIFIED: {
        PaperStatus.TEMPORARILY_PARSED,
        PaperStatus.NUMBERED,
        PaperStatus.DELIVERED,
    },
    PaperStatus.TEMPORARILY_PARSED: {PaperStatus.NUMBERED, PaperStatus.DELIVERED},
    PaperStatus.NUMBERED: {PaperStatus.DELIVERED},
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _identity_part(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    return re.sub(r"[^\w]+", "", normalized)


def _identity_key(
    title: str,
    year: int | None,
    first_author: str | None,
    venue: str | None,
) -> str:
    return "|".join(
        (_identity_part(title), str(year or ""), _identity_part(first_author), _identity_part(venue))
    )


class Registry:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._initialize()

    def _initialize(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS papers (
                paper_id TEXT PRIMARY KEY,
                doi TEXT UNIQUE,
                identity_key TEXT NOT NULL UNIQUE,
                canonical_title TEXT NOT NULL,
                year INTEGER,
                first_author TEXT,
                venue TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS artifacts (
                artifact_id INTEGER PRIMARY KEY AUTOINCREMENT,
                paper_id TEXT NOT NULL REFERENCES papers(paper_id),
                kind TEXT NOT NULL,
                path TEXT,
                sha256 TEXT,
                source_url TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(paper_id, kind, sha256)
            );

            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                mode TEXT NOT NULL,
                spec_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS task_candidates (
                task_id TEXT NOT NULL REFERENCES tasks(task_id),
                paper_id TEXT NOT NULL REFERENCES papers(paper_id),
                score REAL,
                decision TEXT,
                reasons_json TEXT,
                PRIMARY KEY(task_id, paper_id)
            );

            CREATE TABLE IF NOT EXISTS provenance (
                provenance_id INTEGER PRIMARY KEY AUTOINCREMENT,
                paper_id TEXT NOT NULL REFERENCES papers(paper_id),
                source TEXT NOT NULL,
                source_url TEXT,
                payload_json TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS evidence (
                evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT,
                paper_id TEXT NOT NULL REFERENCES papers(paper_id),
                claim_id TEXT,
                relation TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS number_allocations (
                task_id TEXT NOT NULL,
                group_name TEXT NOT NULL,
                paper_id TEXT NOT NULL REFERENCES papers(paper_id),
                number INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(task_id, group_name, paper_id),
                UNIQUE(task_id, group_name, number)
            );

            CREATE TABLE IF NOT EXISTS events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                paper_id TEXT NOT NULL REFERENCES papers(paper_id),
                from_status TEXT,
                to_status TEXT,
                error_code TEXT,
                message TEXT,
                created_at TEXT NOT NULL
            );
            """
        )

    def close(self) -> None:
        self._connection.close()

    def journal_mode(self) -> str:
        row = self._connection.execute("PRAGMA journal_mode").fetchone()
        return str(row[0]).lower()

    def upsert_paper(
        self,
        *,
        title: str,
        doi: str | None = None,
        year: int | None = None,
        first_author: str | None = None,
        venue: str | None = None,
    ) -> str:
        normalized_doi = normalize_doi(doi)
        identity = _identity_key(title, year, first_author, venue)
        timestamp = _now()
        paper_id = uuid.uuid4().hex
        with self._lock:
            self._connection.execute(
                """
                INSERT OR IGNORE INTO papers (
                    paper_id, doi, identity_key, canonical_title, year, first_author, venue,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    paper_id,
                    normalized_doi,
                    identity,
                    title.strip(),
                    year,
                    first_author,
                    venue,
                    PaperStatus.DISCOVERED.value,
                    timestamp,
                    timestamp,
                ),
            )
            if normalized_doi:
                row = self._connection.execute(
                    "SELECT paper_id FROM papers WHERE doi = ?", (normalized_doi,)
                ).fetchone()
            else:
                row = self._connection.execute(
                    "SELECT paper_id FROM papers WHERE identity_key = ?", (identity,)
                ).fetchone()
        if row is None:
            raise RuntimeError("paper upsert did not produce a durable record")
        return str(row["paper_id"])

    def status(self, paper_id: str) -> PaperStatus:
        row = self._connection.execute(
            "SELECT status FROM papers WHERE paper_id = ?", (paper_id,)
        ).fetchone()
        if row is None:
            raise KeyError(paper_id)
        return PaperStatus(row["status"])

    def transition(self, paper_id: str, target: PaperStatus) -> None:
        with self._lock:
            current = self.status(paper_id)
            if current is target:
                return
            if target not in ALLOWED_TRANSITIONS.get(current, set()):
                raise StateTransitionError(f"illegal paper transition: {current.value} -> {target.value}")
            timestamp = _now()
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = self._connection.execute(
                    "UPDATE papers SET status = ?, updated_at = ? WHERE paper_id = ? AND status = ?",
                    (target.value, timestamp, paper_id, current.value),
                )
                if cursor.rowcount != 1:
                    raise StateTransitionError("paper state changed concurrently")
                self._connection.execute(
                    """
                    INSERT INTO events (paper_id, from_status, to_status, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (paper_id, current.value, target.value, timestamp),
                )
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise

    def record_error(self, paper_id: str, code: ErrorCode, message: str) -> None:
        current = self.status(paper_id)
        self._connection.execute(
            """
            INSERT INTO events (
                paper_id, from_status, to_status, error_code, message, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (paper_id, current.value, current.value, code.value, message, _now()),
        )

    def events(self, paper_id: str) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            """
            SELECT from_status, to_status, error_code, message, created_at
            FROM events WHERE paper_id = ? ORDER BY event_id
            """,
            (paper_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def create_verified_paper(self, title: str, doi: str) -> str:
        paper_id = self.upsert_paper(title=title, doi=doi)
        for status in (
            PaperStatus.AUTO_ACCEPTED,
            PaperStatus.RESOLVING,
            PaperStatus.DOWNLOADED,
            PaperStatus.PAIR_VERIFIED,
        ):
            self.transition(paper_id, status)
        return paper_id

    def allocate_number(self, task_id: str, group_name: str, paper_id: str) -> int:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute(
                    """
                    SELECT number FROM number_allocations
                    WHERE task_id = ? AND group_name = ? AND paper_id = ?
                    """,
                    (task_id, group_name, paper_id),
                ).fetchone()
                if row is not None:
                    self._connection.execute("COMMIT")
                    return int(row["number"])
                row = self._connection.execute(
                    """
                    SELECT COALESCE(MAX(number), 0) + 1 AS next_number
                    FROM number_allocations WHERE task_id = ? AND group_name = ?
                    """,
                    (task_id, group_name),
                ).fetchone()
                number = int(row["next_number"])
                self._connection.execute(
                    """
                    INSERT INTO number_allocations (
                        task_id, group_name, paper_id, number, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (task_id, group_name, paper_id, number, _now()),
                )
                self._connection.execute("COMMIT")
                return number
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
