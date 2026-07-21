from __future__ import annotations

import csv
import io
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from acquire_research_papers.artifacts import atomic_write_bytes, sha256_file
from acquire_research_papers.selection import SelectionRecord, SelectionStore


_MANUAL_CODES = frozenset(
    {"access_required", "manual_publisher_download", "unsupported_adapter"}
)
_RETRYABLE_CODES = frozenset({"network_transient", "rate_limited"})


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


@dataclass(frozen=True)
class AcquisitionRunResult:
    status: str
    acquisition_path: Path
    manual_download_path: Path
    retryable_path: Path
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
    ) -> AcquisitionRunResult:
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
            manifest_path=manifest_path,
            total=len(rows),
            delivered=counts["delivered"],
            manual_required=counts["manual_required"],
            retryable=counts["retryable"],
            contract_error=counts["contract_error"],
            complete=complete,
        )
