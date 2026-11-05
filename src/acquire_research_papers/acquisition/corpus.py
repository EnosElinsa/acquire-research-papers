from __future__ import annotations

import csv
import html
import io
import json
import os
import re
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, urlsplit

from acquire_research_papers.artifacts import atomic_write_bytes, sha256_file, validate_pdf
from acquire_research_papers.acquisition.manual_handoff import (
    document_from_selection,
    validate_manual_pair,
)
from acquire_research_papers.acquisition.outcomes import PAUSE_HOST, failure_outcome
from acquire_research_papers.acquisition.router import canonical_landing_url, doi_publisher_host
from acquire_research_papers.models import normalize_doi
from acquire_research_papers.paths import resolve_path
from acquire_research_papers.selection import SelectionRecord, SelectionStore


_MANUAL_CODES = frozenset(
    {"access_required", "manual_publisher_download", "unsupported_adapter"}
)
HOST_PAUSED = "host_paused"
_RETRYABLE_CODES = frozenset(
    {"network_transient", "rate_limited", "automation_error", HOST_PAUSED}
)
_HOST_LABEL = re.compile(r"(?!-)[a-z0-9-]{1,63}(?<!-)\Z", re.IGNORECASE)
_SELECTION_ID = re.compile(r"[0-9a-f]{8,64}\Z")
IN_PROGRESS_STATE = "in_progress"
INTERRUPTED_DIRECTORY = ".arp-interrupted"
# Ledger flag: the last attempt ended access_required because this paper itself was refused.
ACCESS_REFUSED = "access_refused"
MANUAL_PAGE = "manual-download.html"


def _manual_page(rows: list[dict[str, Any]], selection_manifest: Path, destination: Path) -> bytes:
    """A static checklist of the manual-download queue; every value is escaped, no scripts."""
    def link(url: str, text: str) -> str:
        scheme = urlsplit(url).scheme.casefold() if url else ""
        if scheme not in {"http", "https"}:
            return html.escape(text)
        return f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener">' \
               f"{html.escape(text)}</a>"

    items = "\n".join(
        "<tr><td>{n}</td><td>{title}</td><td>{doi}</td><td>{publisher}</td><td>{reason}</td>"
        "<td><code>{pdf}</code><br><code>{bib}</code></td></tr>".format(
            n=index,
            title=link(str(row.get("official_url") or ""), str(row.get("title") or "")),
            doi=html.escape(str(row.get("doi") or "")),
            publisher=html.escape(str(row.get("publisher") or "")),
            reason=html.escape(f"{row.get('error_code', '')}: {row.get('message', '')}"),
            pdf=html.escape(str(row.get("target_pdf") or "")),
            bib=html.escape(str(row.get("target_bibtex") or "")),
        )
        for index, row in enumerate(rows, start=1)
    )
    command = (f'arp manual-fetch --selection "{selection_manifest}" --queue '
               f'--output "{destination}" --from "<folder with the downloads>"')
    open_all = (f'arp manual-fetch --selection "{selection_manifest}" --queue '
                f'--output "{destination}" --open-all')
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Manual downloads ({len(rows)})</title>
<style>body{{font-family:system-ui,sans-serif;margin:2em}}table{{border-collapse:collapse}}
td,th{{border:1px solid #ccc;padding:.4em;vertical-align:top}}code{{font-size:.85em}}</style>
</head><body>
<h1>Manual downloads: {len(rows)} papers</h1>
<p>Open each title, sign in where needed, and download the official PDF and the publisher's raw
BibTeX export into one folder. Then import them all at once:</p>
<pre>{html.escape(command)}</pre>
<p>Or let arp open the official pages of up to 30 papers at once and import each pair from your
Downloads folder as soon as it arrives, in any order:</p>
<pre>{html.escape(open_all)}</pre>
<table><tr><th>#</th><th>Title (official page)</th><th>DOI</th><th>Publisher</th>
<th>Reason</th><th>Delivered as</th></tr>
{items}
</table></body></html>
""".encode("utf-8")


def normalized_state(outcome: Mapping[str, Any]) -> str:
    if outcome.get("status") == "delivered":
        return "delivered"
    code = str(outcome.get("error_code", "contract_error"))
    if code in _MANUAL_CODES:
        return "manual_required"
    if code in _RETRYABLE_CODES:
        return "retryable"
    return "contract_error"


def _public_message(value: Any) -> str:
    return " ".join(str(value or "").split())[:500]


def _official_url(record: SelectionRecord) -> str:
    if record.official_url:
        return record.official_url
    if record.doi:
        return f"https://doi.org/{quote(record.doi, safe='/().;:-_')}"
    return ""


def _publisher_host(record: SelectionRecord) -> str:
    try:
        hostname = urlsplit(canonical_landing_url(_official_url(record))).hostname
    except ValueError:
        return record.publisher
    if hostname and hostname.casefold().rstrip(".") in {"doi.org", "dx.doi.org", "www.doi.org"}:
        # Name the publisher of a DOI-only record offline so --defer-host can match it.
        hostname = doi_publisher_host(record.doi) or hostname
    return hostname or record.publisher


def _normalize_exact_hosts(values: Iterable[str]) -> frozenset[str]:
    normalized: set[str] = set()
    for value in values:
        candidate = str(value).strip().rstrip(".")
        try:
            ascii_host = candidate.encode("idna").decode("ascii").casefold()
        except UnicodeError as exc:
            raise ValueError("deferred publisher must be an exact hostname") from exc
        labels = ascii_host.split(".")
        if (
            not ascii_host
            or len(ascii_host) > 253
            or len(labels) < 2
            or any(not _HOST_LABEL.fullmatch(label) for label in labels)
        ):
            raise ValueError("deferred publisher must be an exact hostname")
        normalized.add(ascii_host)
    return frozenset(normalized)


def _normalized_record_host(record: SelectionRecord) -> str:
    host = _publisher_host(record).strip().rstrip(".")
    try:
        return host.encode("idna").decode("ascii").casefold()
    except UnicodeError:
        return host.casefold()


def _expected_paths(record: SelectionRecord, root: Path) -> dict[str, Path]:
    resolved_root = resolve_path(root)
    paths = {
        "pdf": resolve_path(resolved_root / record.relative_pdf),
        "bibtex": resolve_path(resolved_root / record.relative_bibtex),
        "provenance": resolve_path(resolved_root / record.relative_provenance),
    }
    if any(path == resolved_root or resolved_root not in path.parents for path in paths.values()):
        raise ValueError("selection delivery path escapes the output root")
    return paths


def _read_previous(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    previous: dict[str, dict[str, Any]] = {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict) or not value.get("selection_id"):
                    raise ValueError(
                        f"acquisition manifest row {line_number} has no selection_id"
                    )
                selection_id = str(value["selection_id"])
                if selection_id in previous:
                    raise ValueError("acquisition manifest contains duplicate selection_id")
                previous[selection_id] = value
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("existing acquisition output has an unreadable acquisition manifest") from exc
    return previous


def _read_json_object(path: Path, description: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"existing acquisition output has an unreadable {description}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"existing acquisition output has an unreadable {description}")
    return value


def _write_json_object(path: Path, value: Mapping[str, Any]) -> None:
    atomic_write_bytes(
        path,
        (
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8"),
    )


def _has_unbound_managed_artifacts(
    destination: Path,
    records: tuple[SelectionRecord, ...],
) -> bool:
    managed = (
        "acquisition-manifest.jsonl",
        "manual-download.csv",
        MANUAL_PAGE,
        "retryable-downloads.csv",
        "paper-manifest.csv",
    )
    if any((destination / name).exists() for name in managed):
        return True
    managed_endings = (
        ".pdf",
        ".bib",
        ".provenance.json",
        ".pdf.partial",
        ".bib.partial",
        ".json.partial",
    )
    if any(
        path.is_file()
        and (
            path.name.casefold() == "provenance.json"
            or path.name.casefold().endswith(managed_endings)
        )
        for path in destination.rglob("*")
    ):
        return True
    return any(
        path.exists()
        for record in records
        for path in _expected_paths(record, destination).values()
    )


def _verified_previous(
    record: SelectionRecord,
    row: Mapping[str, Any] | None,
    root: Path,
) -> bool:
    if not row or row.get("state") != "delivered":
        return False
    expected = _expected_paths(record, root)
    for kind, path in expected.items():
        recorded = row.get(kind)
        digest = row.get(f"{kind}_sha256")
        if not recorded or not digest or resolve_path(Path(str(recorded))) != path:
            return False
        if not path.is_file() or sha256_file(path) != digest:
            return False
    return True


def _normalized_identity_text(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _verified_manual_import(
    record: SelectionRecord,
    prior: Mapping[str, Any] | None,
    root: Path,
) -> dict[str, Any] | None:
    if not prior or prior.get("state") != "manual_required":
        return None
    expected = _expected_paths(record, root)
    if not all(path.is_file() for path in expected.values()):
        return None
    try:
        provenance = json.loads(expected["provenance"].read_text(encoding="utf-8"))
        validate_pdf(expected["pdf"])
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(provenance, dict):
        return None
    metadata = provenance.get("metadata")
    if not isinstance(metadata, dict):
        return None
    pdf_sha256 = sha256_file(expected["pdf"])
    bibtex_sha256 = sha256_file(expected["bibtex"])
    try:
        metadata_year = int(metadata.get("year") or 0)
        year_matches = metadata_year == record.year
        if not year_matches:
            year_matches = (
                metadata_year == record.year + 1
                and int(provenance.get("selection_year") or 0) == record.year
                and int(provenance.get("publisher_bibliographic_year") or 0)
                == metadata_year
            )
        identity_matches = (
            _normalized_identity_text(metadata.get("title"))
            == _normalized_identity_text(record.title)
            and year_matches
            and _normalized_identity_text(metadata.get("venue"))
            == _normalized_identity_text(record.venue)
            and normalize_doi(metadata.get("doi")) == normalize_doi(record.doi)
        )
    except (TypeError, ValueError):
        return None
    if not (
        provenance.get("selection_id") == record.selection_id
        and provenance.get("acquisition_method") == "manual_publisher_download"
        and provenance.get("pdf_sha256") == pdf_sha256
        and provenance.get("bibtex_sha256") == bibtex_sha256
        and identity_matches
    ):
        return None
    try:
        validate_manual_pair(
            document_from_selection(record),
            expected["pdf"],
            expected["bibtex"],
            allow_next_issue_year=True,
        )
    except (OSError, UnicodeError, ValueError):
        return None
    return {
        **_identity_row(record),
        "state": "delivered",
        "error_code": "",
        "message": "",
        **{kind: str(path) for kind, path in expected.items()},
        "pdf_sha256": pdf_sha256,
        "bibtex_sha256": bibtex_sha256,
        "provenance_sha256": sha256_file(expected["provenance"]),
    }


def _adopted_delivery(
    record: SelectionRecord,
    prior: Mapping[str, Any] | None,
    root: Path,
) -> dict[str, Any] | None:
    """Recognise a complete pair delivered for this selection before its ledger row was saved."""
    if prior and prior.get("state") == "delivered":
        # A recorded delivery whose files no longer verify was changed after delivery.
        return None
    expected = _expected_paths(record, root)
    if not all(path.is_file() for path in expected.values()):
        return None
    try:
        provenance = json.loads(expected["provenance"].read_text(encoding="utf-8"))
        validate_pdf(expected["pdf"])
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(provenance, dict) or provenance.get("selection_id") != record.selection_id:
        return None
    if provenance.get("acquisition_method") == "manual_publisher_download":
        return _verified_manual_import(record, {"state": "manual_required"}, root)
    metadata = provenance.get("metadata")
    if not isinstance(metadata, dict):
        return None
    pdf_sha256 = sha256_file(expected["pdf"])
    bibtex_sha256 = sha256_file(expected["bibtex"])
    if (
        provenance.get("pdf_sha256") != pdf_sha256
        or provenance.get("bibtex_sha256") != bibtex_sha256
    ):
        return None
    expected_doi = normalize_doi(record.doi)
    delivered_value = metadata.get("doi")
    delivered_doi = normalize_doi(delivered_value) if isinstance(delivered_value, str) else None
    if expected_doi and delivered_doi and expected_doi != delivered_doi:
        return None
    return {
        **_identity_row(record),
        "state": "delivered",
        "error_code": "",
        "message": "",
        **{kind: str(path) for kind, path in expected.items()},
        "pdf_sha256": pdf_sha256,
        "bibtex_sha256": bibtex_sha256,
        "provenance_sha256": sha256_file(expected["provenance"]),
    }


def _quarantine_interrupted(record: SelectionRecord, root: Path) -> list[str]:
    """Move leftovers of this run's own interrupted attempt aside; never delete them."""
    expected = _expected_paths(record, root)
    present = {kind: path for kind, path in expected.items() if path.exists()}
    if not present:
        return []
    if not _SELECTION_ID.fullmatch(record.selection_id):
        raise ValueError("selection ID cannot name an interruption folder")
    resolved_root = resolve_path(root)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    target = resolved_root / INTERRUPTED_DIRECTORY / record.selection_id / stamp
    target.mkdir(parents=True, exist_ok=False)
    moved: list[str] = []
    for kind, path in present.items():
        destination = target / f"{kind}--{path.name}"
        os.replace(path, destination)
        moved.append(destination.relative_to(resolved_root).as_posix())
    return moved


def _in_progress_row(record: SelectionRecord) -> dict[str, Any]:
    return {
        **_identity_row(record),
        "state": IN_PROGRESS_STATE,
        "error_code": "",
        "message": "acquisition started; an interruption leaves this row for resume",
        "pdf": "",
        "bibtex": "",
        "provenance": "",
        "pdf_sha256": "",
        "bibtex_sha256": "",
        "provenance_sha256": "",
    }


def _unverified_reserved_error(record: SelectionRecord, root: Path) -> ValueError:
    resolved_root = resolve_path(root)
    present = [
        path.relative_to(resolved_root).as_posix()
        for path in _expected_paths(record, root).values()
        if path.exists()
    ]
    return ValueError(
        "acquisition output contains an unverified reserved artifact: "
        + ", ".join(present)
        + "; move it out of the delivery root or complete it with manual-fetch --selection"
    )


def _delivered_row(
    record: SelectionRecord,
    outcome: Mapping[str, Any],
    root: Path,
) -> dict[str, Any] | None:
    expected = _expected_paths(record, root)
    digests: dict[str, str] = {}
    for kind, path in expected.items():
        supplied_path = outcome.get(kind)
        supplied_digest = outcome.get(f"{kind}_sha256")
        if (
            not supplied_path
            or resolve_path(Path(str(supplied_path))) != path
            or not path.is_file()
        ):
            return None
        actual_digest = sha256_file(path)
        if not supplied_digest or supplied_digest != actual_digest:
            return None
        digests[f"{kind}_sha256"] = actual_digest
    return {
        **_identity_row(record),
        "state": "delivered",
        "error_code": "",
        "message": "",
        **{kind: str(path) for kind, path in expected.items()},
        **digests,
    }


def _identity_row(record: SelectionRecord) -> dict[str, Any]:
    return {
        "selection_id": record.selection_id,
        "ordinal": record.ordinal,
        "key": record.key,
        "title": record.title,
        "doi": record.doi or "",
        "official_url": _official_url(record),
        "publisher": _publisher_host(record),
        "target_pdf": record.relative_pdf,
        "target_bibtex": record.relative_bibtex,
    }


def _failure_row(record: SelectionRecord, outcome: Mapping[str, Any]) -> dict[str, Any]:
    code = str(outcome.get("error_code", "contract_error"))
    return {
        **_identity_row(record),
        "state": normalized_state(outcome),
        "error_code": code,
        "message": _public_message(outcome.get("message")),
        "pdf": "",
        "bibtex": "",
        "provenance": "",
        "pdf_sha256": "",
        "bibtex_sha256": "",
        "provenance_sha256": "",
    }


def _jsonl(rows: list[dict[str, Any]]) -> bytes:
    return "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
    ).encode("utf-8")


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    atomic_write_bytes(path, buffer.getvalue().encode("utf-8-sig"))


def _provenance_urls(row: Mapping[str, Any]) -> dict[str, str]:
    path_value = row.get("provenance")
    if row.get("state") != "delivered" or not path_value:
        return {}
    try:
        payload = json.loads(Path(str(path_value)).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        field: str(payload.get(field) or "")
        for field in (
            "official_landing_url",
            "official_pdf_url",
            "official_bibtex_url",
        )
    }


def _paper_manifest_row(
    record: SelectionRecord,
    acquisition_row: Mapping[str, Any],
) -> dict[str, Any]:
    relative_pdf = PurePosixPath(record.relative_pdf)
    urls = _provenance_urls(acquisition_row)
    return {
        "folder": relative_pdf.parent.as_posix(),
        "number": relative_pdf.stem,
        "title": record.title,
        "year": record.year,
        "venue": record.venue,
        "doi": record.doi or "",
        "official_landing_url": urls.get("official_landing_url")
        or _official_url(record),
        "official_pdf_url": urls.get("official_pdf_url", ""),
        "official_bibtex_url": urls.get("official_bibtex_url", ""),
        "keywords": "; ".join(record.keywords),
        "state": acquisition_row["state"],
        "pdf": record.relative_pdf,
        "bibtex": record.relative_bibtex,
    }


@dataclass(frozen=True)
class AcquisitionRunResult:
    status: str
    acquisition_path: Path
    manual_download_path: Path | None
    retryable_path: Path | None
    paper_manifest_path: Path
    manifest_path: Path
    total: int
    delivered: int
    manual_required: int
    retryable: int
    contract_error: int
    complete: bool
    # manual_required papers kept from an earlier refusal instead of being requested again.
    not_retried: int = 0
    # A checklist page with the official link of every manual-download item.
    manual_page_path: Path | None = None


def _write_acquisition_outputs(
    destination: Path,
    selection: SelectionStore,
    rows: list[dict[str, Any]],
    *,
    selection_sha256: str,
    selected_snapshot: bytes,
    not_retried: int = 0,
) -> AcquisitionRunResult:
    """Write the final ledger, queues, inventory, and delivery manifest of one run."""
    acquisition_path = destination / "acquisition-manifest.jsonl"
    manifest_path = destination / "delivery-manifest.json"
    binding_path = destination / "selection-binding.json"
    manual_rows = [row for row in rows if row["state"] == "manual_required"]
    retryable_rows = [row for row in rows if row["state"] == "retryable"]
    atomic_write_bytes(acquisition_path, _jsonl(rows))

    identity_fields = [
        "selection_id",
        "ordinal",
        "title",
        "doi",
        "official_url",
        "publisher",
    ]
    manual_path = destination / "manual-download.csv"
    _write_csv(
        manual_path,
        [*identity_fields, "reason", "message", "target_pdf", "target_bibtex"],
        [
            {
                **row,
                "reason": row["error_code"],
            }
            for row in manual_rows
        ],
    )
    retryable_path = destination / "retryable-downloads.csv"
    _write_csv(
        retryable_path,
        [*identity_fields, "reason", "message"],
        [{**row, "reason": row["error_code"]} for row in retryable_rows],
    )
    manual_page_path = destination / MANUAL_PAGE
    if manual_rows:
        atomic_write_bytes(manual_page_path,
                           _manual_page(manual_rows, selection.manifest_path, destination))
    else:
        manual_page_path.unlink(missing_ok=True)
        manual_page_path = None
    if not manual_rows:
        manual_path.unlink(missing_ok=True)
        manual_path = None
    if not retryable_rows:
        retryable_path.unlink(missing_ok=True)
        retryable_path = None
    paper_manifest_path = destination / "paper-manifest.csv"
    _write_csv(
        paper_manifest_path,
        [
            "folder",
            "number",
            "title",
            "year",
            "venue",
            "doi",
            "official_landing_url",
            "official_pdf_url",
            "official_bibtex_url",
            "keywords",
            "state",
            "pdf",
            "bibtex",
        ],
        [
            _paper_manifest_row(record, row)
            for record, row in zip(selection.records, rows, strict=True)
        ],
    )

    counts = {
        state: sum(row["state"] == state for row in rows)
        for state in ("delivered", "manual_required", "retryable", "contract_error")
    }
    complete = counts["delivered"] == len(rows)
    status = "delivered" if complete else "partial"
    manifest = {
        "schema_version": 1,
        "phase": "acquisition",
        "status": status,
        "selection_sha256": selection_sha256,
        "total": len(rows),
        **counts,
        "not_retried": not_retried,
        "complete": complete,
        "acquisition_manifest": acquisition_path.name,
        "manual_download": manual_path.name if manual_path else None,
        "manual_download_page": manual_page_path.name if manual_page_path else None,
        "retryable_downloads": retryable_path.name if retryable_path else None,
        "paper_manifest": paper_manifest_path.name,
        "selection_binding": binding_path.name,
    }
    _write_json_object(manifest_path, manifest)
    if selection.selected_path.read_bytes() != selected_snapshot:
        raise ValueError("frozen selection changed during acquisition")
    return AcquisitionRunResult(
        status=status,
        acquisition_path=acquisition_path,
        manual_download_path=manual_path,
        retryable_path=retryable_path,
        paper_manifest_path=paper_manifest_path,
        manifest_path=manifest_path,
        total=len(rows),
        delivered=counts["delivered"],
        manual_required=counts["manual_required"],
        retryable=counts["retryable"],
        contract_error=counts["contract_error"],
        complete=complete,
        not_retried=not_retried,
        manual_page_path=manual_page_path,
    )


class _HostGuard:
    """Space requests per publisher host and stop contacting a host that keeps failing."""

    def __init__(
        self,
        *,
        min_interval_seconds: float,
        transient_failure_limit: int,
        sleeper: Callable[[float], None],
        monotonic: Callable[[], float],
    ) -> None:
        self.min_interval_seconds = max(0.0, min_interval_seconds)
        self.transient_failure_limit = max(1, transient_failure_limit)
        self._sleeper = sleeper
        self._monotonic = monotonic
        self._last_call: dict[str, float] = {}
        self._streak: dict[str, int] = {}
        self._paused: dict[str, dict[str, str]] = {}

    def paused(self, host: str) -> dict[str, str] | None:
        pause = self._paused.get(host)
        return dict(pause) if pause else None

    def wait(self, host: str) -> None:
        previous = self._last_call.get(host)
        if previous is not None and self.min_interval_seconds:
            remaining = self.min_interval_seconds - (self._monotonic() - previous)
            if remaining > 0:
                self._sleeper(remaining)

    def record(self, host: str, outcome: Mapping[str, Any]) -> None:
        self._last_call[host] = self._monotonic()
        state = normalized_state(outcome)
        if outcome.get(PAUSE_HOST):
            self._paused[host] = {
                "error_code": "access_required",
                "message": f"{host} paused for this run after an institution login failure; "
                "fix the institution profile or log in, then rerun",
            }
        elif outcome.get("error_code") == "rate_limited":
            self._paused[host] = {
                "error_code": HOST_PAUSED,
                "message": f"{host} paused for this run after HTTP 429; rerun later",
            }
        elif state == "retryable":
            self._streak[host] = self._streak.get(host, 0) + 1
            if self._streak[host] >= self.transient_failure_limit:
                self._paused[host] = {
                    "error_code": HOST_PAUSED,
                    "message": f"{host} paused for this run after {self._streak[host]} "
                    "consecutive transient failures; rerun later",
                }
        else:
            self._streak[host] = 0


def _attempt_by_host(
    records: list[SelectionRecord],
    attempt: Callable[[SelectionRecord], None],
    parallel: int,
) -> None:
    """Attempt each host's papers in selection order, up to ``parallel`` hosts at once.

    One worker owns a host, so per-host spacing, pauses, and a shared institution browser
    are used by one thread at a time. A failing worker stops the others before their next paper.
    """
    groups: dict[str, list[SelectionRecord]] = {}
    for record in records:
        groups.setdefault(_normalized_record_host(record), []).append(record)
    stop = threading.Event()

    def work(host_records: list[SelectionRecord]) -> None:
        for record in host_records:
            if stop.is_set():
                return
            attempt(record)

    executor = ThreadPoolExecutor(max_workers=min(parallel, len(groups) or 1),
                                  thread_name_prefix="arp-host")
    pending = {executor.submit(work, host_records) for host_records in groups.values()}
    try:
        while pending:
            # A bounded wait keeps the main thread responsive to Ctrl+C and job stop.
            done, pending = wait(pending, timeout=0.5, return_when=FIRST_EXCEPTION)
            for future in done:
                future.result()
    except BaseException:
        stop.set()
        executor.shutdown(wait=False, cancel_futures=True)
        raise
    executor.shutdown(wait=True)


class CorpusAcquisitionWorkflow:
    """Acquire only records in a hash-verified frozen selection."""

    def __init__(
        self,
        *,
        acquirer: Callable[[SelectionRecord, Path], dict[str, Any]],
        min_host_interval_seconds: float = 0.0,
        transient_failure_limit: int = 3,
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        max_parallel_hosts: int = 1,
    ) -> None:
        self.acquirer = acquirer
        self.max_parallel_hosts = max(1, max_parallel_hosts)
        self.min_host_interval_seconds = min_host_interval_seconds
        self.transient_failure_limit = transient_failure_limit
        self._sleeper = sleeper
        self._monotonic = monotonic

    def run(
        self,
        selection_manifest: Path,
        output: Path,
        *,
        deferred_hosts: Iterable[str] = (),
        retry_manual: bool = False,
        parallel_hosts: int | None = None,
    ) -> AcquisitionRunResult:
        deferred = _normalize_exact_hosts(deferred_hosts)
        not_retried = 0
        selection = SelectionStore.load(selection_manifest)
        selected_snapshot = selection.selected_path.read_bytes()
        destination = resolve_path(output)
        destination.mkdir(parents=True, exist_ok=True)
        selection_sha256 = str(selection.manifest["selected_sha256"])
        binding_path = destination / "selection-binding.json"
        manifest_path = destination / "delivery-manifest.json"
        existing_manifest = (
            _read_json_object(manifest_path, "delivery manifest")
            if manifest_path.is_file()
            else None
        )
        if existing_manifest is not None:
            if (
                existing_manifest.get("schema_version") != 1
                or existing_manifest.get("phase") != "acquisition"
            ):
                raise ValueError(
                    "existing acquisition output has an unreadable delivery manifest"
                )
            if existing_manifest.get("selection_sha256") != selection_sha256:
                raise ValueError(
                    "acquisition output belongs to a different frozen selection"
                )
        if binding_path.is_file():
            binding = _read_json_object(binding_path, "selection binding")
            if (
                binding.get("schema_version") != 1
                or binding.get("phase") != "acquisition_binding"
            ):
                raise ValueError(
                    "existing acquisition output has an unreadable selection binding"
                )
            if binding.get("selection_sha256") != selection_sha256:
                raise ValueError(
                    "acquisition output belongs to a different frozen selection"
                )
        else:
            if existing_manifest is None and _has_unbound_managed_artifacts(
                destination, selection.records
            ):
                raise ValueError(
                    "acquisition output contains unbound managed artifacts"
                )
            _write_json_object(
                binding_path,
                {
                    "schema_version": 1,
                    "phase": "acquisition_binding",
                    "selection_sha256": selection_sha256,
                },
            )
        acquisition_path = destination / "acquisition-manifest.jsonl"
        previous = _read_previous(acquisition_path)
        selection_ids = {record.selection_id for record in selection.records}
        if set(previous) - selection_ids:
            raise ValueError(
                "existing acquisition output has an unreadable acquisition manifest"
            )

        # The ledger is checkpointed after every paper so an interrupted run can resume.
        _write_json_object(
            manifest_path,
            {
                "schema_version": 1,
                "phase": "acquisition",
                "status": IN_PROGRESS_STATE,
                "selection_sha256": selection_sha256,
                "total": len(selection.records),
                "acquisition_manifest": acquisition_path.name,
                "selection_binding": binding_path.name,
            },
        )
        order = [record.selection_id for record in selection.records]
        ledger: dict[str, dict[str, Any]] = dict(previous)
        guard = _HostGuard(
            min_interval_seconds=self.min_host_interval_seconds,
            transient_failure_limit=self.transient_failure_limit,
            sleeper=self._sleeper,
            monotonic=self._monotonic,
        )

        ledger_lock = threading.Lock()

        def checkpoint(selection_id: str, row: dict[str, Any]) -> None:
            with ledger_lock:
                ledger[selection_id] = row
                atomic_write_bytes(
                    acquisition_path,
                    _jsonl([ledger[key] for key in order if key in ledger]),
                )

        def finish(record: SelectionRecord, outcome: Mapping[str, Any],
                   attempted: bool) -> dict[str, Any]:
            if normalized_state(outcome) == "delivered":
                row = _delivered_row(record, outcome, destination)
                if row is None:
                    outcome = {
                        "error_code": "contract_error",
                        "message": "delivered outcome does not match reserved verified paths",
                    }
                    row = _failure_row(record, outcome)
            else:
                row = _failure_row(record, outcome)
                # Only a refusal of this paper is remembered. Deferral, a paused host, and an
                # institution login failure (which pauses the host) are retried on rerun.
                row[ACCESS_REFUSED] = (
                    attempted
                    and row["error_code"] == "access_required"
                    and not outcome.get(PAUSE_HOST)
                )
            if row["state"] != "delivered" and any(
                path.exists() for path in _expected_paths(record, destination).values()
            ):
                raise _unverified_reserved_error(record, destination)
            checkpoint(record.selection_id, row)
            return row

        def attempt(record: SelectionRecord) -> None:
            publisher_host = _normalized_record_host(record)
            paused = guard.paused(publisher_host)
            if paused is not None:
                outcome, attempted = paused, False
            else:
                guard.wait(publisher_host)
                checkpoint(record.selection_id, _in_progress_row(record))
                try:
                    outcome = self.acquirer(record, destination)
                except Exception as exc:
                    outcome = failure_outcome(exc)
                guard.record(publisher_host, outcome)
                attempted = True
            settled_rows[record.selection_id] = finish(record, outcome, attempted)

        # First settle everything that needs no publisher contact, in selection order.
        settled_rows: dict[str, dict[str, Any]] = {}
        to_attempt: list[SelectionRecord] = []
        for record in selection.records:
            prior = previous.get(record.selection_id)
            if prior is not None and _verified_previous(record, prior, destination):
                settled_rows[record.selection_id] = dict(prior)
                continue
            settled = _verified_manual_import(record, prior, destination) or _adopted_delivery(
                record, prior, destination
            )
            if settled is not None:
                checkpoint(record.selection_id, settled)
                settled_rows[record.selection_id] = settled
                continue
            if prior and prior.get("state") == IN_PROGRESS_STATE:
                # Leftovers of this output's own interrupted attempt; keep them for inspection.
                _quarantine_interrupted(record, destination)
            if any(
                path.exists() for path in _expected_paths(record, destination).values()
            ):
                raise _unverified_reserved_error(record, destination)
            if not retry_manual and prior and prior.get(ACCESS_REFUSED) is True:
                # The publisher or institution refused this paper last time; asking again would
                # reopen a login or repeat the refusal. --retry-manual asks again.
                settled_rows[record.selection_id] = dict(prior)
                not_retried += 1
                continue
            publisher_host = _normalized_record_host(record)
            if publisher_host in deferred:
                settled_rows[record.selection_id] = finish(record, {
                    "error_code": "access_required",
                    "message": f"publisher host deferred for this run: {publisher_host}",
                }, False)
                continue
            to_attempt.append(record)

        # Then contact publishers: one host at a time per worker, several hosts at once.
        parallel = max(1, int(parallel_hosts or self.max_parallel_hosts))
        if parallel == 1:
            for record in to_attempt:
                attempt(record)
        else:
            _attempt_by_host(to_attempt, attempt, parallel)
        rows = [settled_rows[record.selection_id] for record in selection.records]

        return _write_acquisition_outputs(
            destination,
            selection,
            rows,
            selection_sha256=selection_sha256,
            selected_snapshot=selected_snapshot,
            not_retried=not_retried,
        )


@dataclass(frozen=True)
class ManualQueue:
    """Manual-download items of one finished acquisition output, in selection order."""

    destination: Path
    waiting: tuple[SelectionRecord, ...]
    already_imported: tuple[SelectionRecord, ...]


def _finished_ledger(selection: SelectionStore, destination: Path) -> dict[str, dict[str, Any]]:
    manifest_path = destination / "delivery-manifest.json"
    binding_path = destination / "selection-binding.json"
    if not manifest_path.is_file() or not binding_path.is_file():
        raise ValueError(
            "no acquisition output for this selection; run acquire with this selection and "
            "output first"
        )
    selection_sha256 = str(selection.manifest["selected_sha256"])
    manifest = _read_json_object(manifest_path, "delivery manifest")
    binding = _read_json_object(binding_path, "selection binding")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("phase") != "acquisition"
        or binding.get("schema_version") != 1
        or binding.get("phase") != "acquisition_binding"
    ):
        raise ValueError("existing acquisition output has an unreadable delivery manifest")
    if (
        manifest.get("selection_sha256") != selection_sha256
        or binding.get("selection_sha256") != selection_sha256
    ):
        raise ValueError("acquisition output belongs to a different frozen selection")
    if manifest.get("status") == IN_PROGRESS_STATE:
        raise ValueError(
            "acquisition was interrupted; rerun acquire with the same output before "
            "importing its manual-download queue"
        )
    previous = _read_previous(destination / "acquisition-manifest.jsonl")
    if set(previous) != {record.selection_id for record in selection.records}:
        raise ValueError("existing acquisition output has an unreadable acquisition manifest")
    return previous


def load_manual_queue(selection_manifest: Path, output: Path) -> ManualQueue:
    """Read the manual-download items of a finished acquisition without changing it."""
    selection = SelectionStore.load(selection_manifest)
    destination = resolve_path(output)
    ledger = _finished_ledger(selection, destination)
    waiting: list[SelectionRecord] = []
    imported: list[SelectionRecord] = []
    for record in selection.records:
        row = ledger[record.selection_id]
        if row.get("state") != "manual_required":
            continue
        present = [path for path in _expected_paths(record, destination).values() if path.exists()]
        if not present:
            waiting.append(record)
        elif _verified_manual_import(record, row, destination) is not None:
            imported.append(record)
        else:
            raise _unverified_reserved_error(record, destination)
    return ManualQueue(destination, tuple(waiting), tuple(imported))


def reconcile_manual_imports(selection_manifest: Path, output: Path) -> AcquisitionRunResult:
    """Record verified manual imports in the ledger and queues; contact no publisher."""
    selection = SelectionStore.load(selection_manifest)
    selected_snapshot = selection.selected_path.read_bytes()
    destination = resolve_path(output)
    ledger = _finished_ledger(selection, destination)
    rows: list[dict[str, Any]] = []
    for record in selection.records:
        row = dict(ledger[record.selection_id])
        if row.get("state") == "manual_required":
            row = _verified_manual_import(record, row, destination) or row
        rows.append(row)
    return _write_acquisition_outputs(
        destination,
        selection,
        rows,
        selection_sha256=str(selection.manifest["selected_sha256"]),
        selected_snapshot=selected_snapshot,
    )
