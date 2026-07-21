from __future__ import annotations

import csv
import io
import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, urlsplit

from acquire_research_papers.artifacts import atomic_write_bytes, sha256_file
from acquire_research_papers.selection import SelectionRecord, SelectionStore


_MANUAL_CODES = frozenset(
    {"access_required", "manual_publisher_download", "unsupported_adapter"}
)
_RETRYABLE_CODES = frozenset({"network_transient", "rate_limited"})
_HOST_LABEL = re.compile(r"(?!-)[a-z0-9-]{1,63}(?<!-)\Z", re.IGNORECASE)


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
        return urlsplit(_official_url(record)).hostname or record.publisher
    except ValueError:
        return record.publisher


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
    resolved_root = root.resolve()
    paths = {
        "pdf": (resolved_root / record.relative_pdf).resolve(),
        "bibtex": (resolved_root / record.relative_bibtex).resolve(),
        "provenance": (resolved_root / record.relative_provenance).resolve(),
    }
    if any(path == resolved_root or resolved_root not in path.parents for path in paths.values()):
        raise ValueError("selection delivery path escapes the output root")
    return paths


def _read_previous(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    previous: dict[str, dict[str, Any]] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            value = json.loads(line)
            if isinstance(value, dict) and value.get("selection_id"):
                previous[str(value["selection_id"])] = value
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return previous


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
        if not recorded or not digest or Path(str(recorded)).resolve() != path:
            return False
        if not path.is_file() or sha256_file(path) != digest:
            return False
    return True


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
        if not supplied_path or Path(str(supplied_path)).resolve() != path or not path.is_file():
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
    manual_download_path: Path
    retryable_path: Path
    paper_manifest_path: Path
    manifest_path: Path
    total: int
    delivered: int
    manual_required: int
    retryable: int
    contract_error: int
    complete: bool


class CorpusAcquisitionWorkflow:
    """Acquire only records in a hash-verified frozen selection."""

    def __init__(
        self,
        *,
        acquirer: Callable[[SelectionRecord, Path], dict[str, Any]],
    ) -> None:
        self.acquirer = acquirer

    def run(
        self,
        selection_manifest: Path,
        output: Path,
        *,
        deferred_hosts: Iterable[str] = (),
    ) -> AcquisitionRunResult:
        deferred = _normalize_exact_hosts(deferred_hosts)
        selection = SelectionStore.load(selection_manifest)
        selected_snapshot = selection.selected_path.read_bytes()
        destination = output.resolve()
        destination.mkdir(parents=True, exist_ok=True)
        acquisition_path = destination / "acquisition-manifest.jsonl"
        previous = _read_previous(acquisition_path)

        rows: list[dict[str, Any]] = []
        for record in selection.records:
            prior = previous.get(record.selection_id)
            if _verified_previous(record, prior, destination):
                rows.append(dict(prior))
                continue
            publisher_host = _normalized_record_host(record)
            if publisher_host in deferred:
                outcome = {
                    "error_code": "access_required",
                    "message": f"publisher host deferred for this run: {publisher_host}",
                }
            else:
                try:
                    outcome = self.acquirer(record, destination)
                except Exception:
                    outcome = {
                        "error_code": "contract_error",
                        "message": "acquirer failed for the selected paper",
                    }
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
            rows.append(row)

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
        manifest_path = destination / "delivery-manifest.json"
        manifest = {
            "schema_version": 1,
            "phase": "acquisition",
            "status": status,
            "selection_sha256": selection.manifest["selected_sha256"],
            "total": len(rows),
            **counts,
            "complete": complete,
            "acquisition_manifest": acquisition_path.name,
            "manual_download": manual_path.name,
            "retryable_downloads": retryable_path.name,
            "paper_manifest": paper_manifest_path.name,
        }
        atomic_write_bytes(
            manifest_path,
            (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
                "utf-8"
            ),
        )
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
        )
