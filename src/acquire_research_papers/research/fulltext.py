from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from acquire_research_papers.acquisition.corpus import (
    AcquisitionRunResult,
    CorpusAcquisitionWorkflow,
)
from acquire_research_papers.artifacts import (
    InvalidPdfError,
    atomic_write_bytes,
    sha256_file,
)
from acquire_research_papers.mineru import MineruCache, MineruExtractionError
from acquire_research_papers.research.state import (
    read_run_manifest,
    update_run_manifest,
    validate_review_audit,
    write_json,
)
from acquire_research_papers.selection import SelectionStore


@dataclass(frozen=True)
class ResearchFullTextResult:
    status: str
    acquisition: AcquisitionRunResult
    full_text_manifest: Path
    manifest_path: Path
    parsed: int
    pending: int
    acquisition_pending: int
    parsing_pending: int


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("manifest row is not an object")
            rows.append(row)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("acquisition manifest could not be read") from exc
    return rows


class ResearchFullTextWorkflow:
    """Acquire a frozen research selection, then parse verified PDFs through MinerU."""

    def __init__(
        self,
        *,
        acquisition: CorpusAcquisitionWorkflow,
        mineru_cache: MineruCache,
    ) -> None:
        self.acquisition = acquisition
        self.mineru_cache = mineru_cache

    def run(
        self,
        root: Path,
        *,
        deferred_hosts: tuple[str, ...] | list[str] = (),
    ) -> ResearchFullTextResult:
        destination = root.resolve()
        run = read_run_manifest(destination)
        selection_value = str(run.get("selection_manifest") or "")
        selection_path = (destination / selection_value).resolve()
        if not selection_value or destination not in selection_path.parents:
            raise ValueError("research run has no safe frozen selection")
        selection = SelectionStore.load(selection_path)
        if (
            selection.manifest.get("phase") != "research-review"
            or selection.manifest.get("candidate_snapshot_sha256")
            != run["candidates_sha256"]
        ):
            raise ValueError("research selection is not bound to this candidate snapshot")
        validate_review_audit(destination, selection.manifest)
        acquisition = self.acquisition.run(
            selection_path,
            destination / "acquisition",
            deferred_hosts=deferred_hosts,
        )
        acquisition_rows = {
            str(row.get("selection_id") or ""): row
            for row in _read_jsonl(acquisition.acquisition_path)
        }
        rows: list[dict[str, Any]] = []
        for record in selection.records:
            acquired = acquisition_rows.get(record.selection_id) or {}
            base = {
                "schema_version": 1,
                "selection_id": record.selection_id,
                "paper_id": record.key,
                "title": record.title,
                "pdf_sha256": "",
                "markdown_sha256": "",
                "pdf": "",
                "markdown": "",
                "mode": "",
            }
            if acquired.get("state") != "delivered":
                rows.append(
                    {
                        **base,
                        "state": "pending",
                        "reason": str(acquired.get("error_code") or "acquisition_required"),
                    }
                )
                continue
            pdf = Path(str(acquired.get("pdf") or "")).resolve()
            if not pdf.is_file() or sha256_file(pdf) != acquired.get("pdf_sha256"):
                raise ValueError("delivered research PDF no longer matches acquisition SHA-256")
            try:
                parsed = self.mineru_cache.parse(pdf)
            except (MineruExtractionError, InvalidPdfError) as exc:
                rows.append(
                    {
                        **base,
                        "state": "pending",
                        "pdf": str(pdf),
                        "pdf_sha256": str(acquired["pdf_sha256"]),
                        "reason": type(exc).__name__,
                    }
                )
                continue
            rows.append(
                {
                    **base,
                    "state": "parsed",
                    "pdf": str(pdf),
                    "pdf_sha256": str(acquired["pdf_sha256"]),
                    "markdown": str(parsed.markdown.resolve()),
                    "markdown_sha256": sha256_file(parsed.markdown),
                    "mode": parsed.mode,
                    "reason": "",
                }
            )
        full_text_manifest = destination / "full-text-manifest.jsonl"
        atomic_write_bytes(
            full_text_manifest,
            b"".join(
                json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n"
                for row in rows
            ),
        )
        parsed_count = sum(row["state"] == "parsed" for row in rows)
        pending_count = len(rows) - parsed_count
        parsing_pending_count = sum(
            row["state"] == "pending" and bool(row.get("pdf_sha256"))
            for row in rows
        )
        acquisition_pending_count = pending_count - parsing_pending_count
        if acquisition_pending_count:
            status = "acquisition_required"
        elif parsing_pending_count:
            status = "parsing_required"
        else:
            status = "evidence_required"
        manifest_path = destination / "full-text-run.json"
        write_json(
            manifest_path,
            {
                "schema_version": 1,
                "phase": "full-text",
                "status": status,
                "candidate_snapshot_sha256": run["candidates_sha256"],
                "selection_sha256": selection.manifest["selected_sha256"],
                "acquisition_manifest": str(
                    acquisition.manifest_path.relative_to(destination)
                ),
                "full_text_manifest": full_text_manifest.name,
                "full_text_sha256": sha256_file(full_text_manifest),
                "parsed": parsed_count,
                "pending": pending_count,
                "acquisition_pending": acquisition_pending_count,
                "parsing_pending": parsing_pending_count,
            },
        )
        update_run_manifest(
            destination,
            phase="full-text",
            status=status,
            full_text_run=manifest_path.name,
            full_text_manifest=full_text_manifest.name,
            full_text_sha256=sha256_file(full_text_manifest),
        )
        return ResearchFullTextResult(
            status=status,
            acquisition=acquisition,
            full_text_manifest=full_text_manifest,
            manifest_path=manifest_path,
            parsed=parsed_count,
            pending=pending_count,
            acquisition_pending=acquisition_pending_count,
            parsing_pending=parsing_pending_count,
        )
