from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from acquire_research_papers.artifacts import atomic_write_bytes, sha256_file
from acquire_research_papers.discovery.contracts import CandidateMetadata
from acquire_research_papers.research.delivery import ResearchDelivery
from acquire_research_papers.research.evidence import EvidenceRecord
from acquire_research_papers.research.planner import ResearchPlanner
from acquire_research_papers.research.state import (
    claim_ids,
    read_run_manifest,
    update_run_manifest,
    validate_record,
    validate_review_audit,
    write_json,
)
from acquire_research_papers.review_contracts import review_metadata
from acquire_research_papers.selection import SelectionRecord, SelectionStore


@dataclass(frozen=True)
class ResearchEvidenceResult:
    status: str
    manifest_path: Path
    reviewed_path: Path
    pending_path: Path
    evidence_map: Path
    nearest_work_matrix: Path
    gap_analysis: Path
    claim_coverage: Path
    reviewed: int
    pending: int
    evidence_records: int


def _read_jsonl(path: Path, description: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{description} row must be an object")
            rows.append(value)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{description} could not be read as JSON Lines") from exc
    return rows


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _candidate(record: SelectionRecord) -> CandidateMetadata:
    return CandidateMetadata(
        key=record.selection_id,
        title=record.title,
        year=record.year,
        venue=record.venue,
        relevance_score=1.0,
        hard_gates_passed=True,
        evidence_fields=record.evidence_fields,
        doi=record.doi,
        official_url=record.official_url,
        authors=record.authors,
        abstract=record.abstract,
        keywords=record.keywords,
        publication_type=record.publication_type,
        track=record.track,
        publication_date=record.publication_date,
    )


class ResearchEvidenceWorkflow:
    """Import agent evidence only when it matches the frozen parsed full text."""

    def run(self, root: Path, decisions_path: Path) -> ResearchEvidenceResult:
        destination = root.resolve()
        run = read_run_manifest(destination)
        fulltext_name = str(run.get("full_text_manifest") or "")
        fulltext_path = (destination / fulltext_name).resolve()
        if fulltext_path.parent != destination or not fulltext_path.is_file():
            raise ValueError("research run has no valid full-text manifest")
        if sha256_file(fulltext_path) != run.get("full_text_sha256"):
            raise ValueError("research full-text manifest SHA-256 mismatch")
        selection_path = (destination / str(run.get("selection_manifest") or "")).resolve()
        if destination not in selection_path.parents:
            raise ValueError("research run has no safe frozen selection")
        selection = SelectionStore.load(selection_path)
        validate_review_audit(destination, selection.manifest)
        fulltext_rows = {
            str(row.get("selection_id") or ""): row
            for row in _read_jsonl(fulltext_path, "research full-text manifest")
        }
        reviewed_path = destination / "validated-evidence-reviews.jsonl"
        prior_rows = (
            _read_jsonl(reviewed_path, "validated research evidence")
            if reviewed_path.is_file()
            else []
        )
        decision_rows = _read_jsonl(decisions_path, "research evidence decisions")
        decisions: dict[str, dict[str, Any]] = {}
        for source_rows in (prior_rows, decision_rows):
            seen: set[str] = set()
            for row in source_rows:
                validate_record(row, "research-evidence-review.schema.json")
                review_metadata(row)
                selection_id = str(row.get("selection_id") or "")
                if not selection_id or selection_id in seen:
                    raise ValueError(
                        "research evidence has a missing or duplicate selection_id"
                    )
                seen.add(selection_id)
                decisions[selection_id] = row
        known = {record.selection_id for record in selection.records}
        if set(decisions) - known:
            raise ValueError("research evidence references an unknown selected paper")

        valid_claims = set(claim_ids(run["brief"]))
        evidence: list[EvidenceRecord] = []
        validated_reviews: list[dict[str, Any]] = []
        pending_rows: list[dict[str, str]] = []
        for record in selection.records:
            fulltext = fulltext_rows.get(record.selection_id) or {}
            decision = decisions.get(record.selection_id)
            if fulltext.get("state") != "parsed":
                if decision is not None:
                    raise ValueError(
                        "research evidence cannot review a paper with pending full text"
                    )
                pending_rows.append(
                    {
                        "selection_id": record.selection_id,
                        "title": record.title,
                        "reason": str(fulltext.get("reason") or "full text is not parsed"),
                    }
                )
                continue
            if decision is None:
                pending_rows.append(
                    {
                        "selection_id": record.selection_id,
                        "title": record.title,
                        "reason": "agent full-text evidence review required",
                    }
                )
                continue
            if decision.get("full_text_sha256") != fulltext.get("pdf_sha256"):
                raise ValueError("research evidence full-text SHA-256 mismatch")
            if decision.get("markdown_sha256") != fulltext.get("markdown_sha256"):
                raise ValueError("research evidence Markdown SHA-256 mismatch")
            status = str(decision.get("review_status") or "")
            if status not in {"reviewed", "insufficient-text"}:
                raise ValueError("research evidence review_status is unsupported")
            summary = str(decision.get("summary") or "").strip()
            if not summary:
                raise ValueError("research evidence review summary is required")
            markdown = Path(str(fulltext.get("markdown") or "")).resolve()
            if not markdown.is_file() or sha256_file(markdown) != fulltext.get(
                "markdown_sha256"
            ):
                raise ValueError("research Markdown no longer matches its SHA-256")
            markdown_text = _normalized_text(markdown.read_text(encoding="utf-8"))
            records_payload = decision.get("records") or []
            if not isinstance(records_payload, list):
                raise ValueError("research evidence records must be an array")
            if status == "insufficient-text" and records_payload:
                raise ValueError("insufficient-text review cannot contain evidence records")
            validated_records: list[dict[str, Any]] = []
            for payload in records_payload:
                if not isinstance(payload, dict):
                    raise ValueError("research evidence record must be an object")
                evidence_record = EvidenceRecord(**payload).validate()
                if evidence_record.paper_id != record.selection_id:
                    raise ValueError("research evidence paper_id does not match selection_id")
                if evidence_record.claim_id not in valid_claims:
                    raise ValueError("research evidence references an unknown claim")
                if evidence_record.read_scope != "full-text":
                    raise ValueError("research evidence records must come from full text")
                excerpt = _normalized_text(evidence_record.excerpt)
                if excerpt and excerpt not in markdown_text:
                    raise ValueError("research evidence excerpt was not found in bound Markdown")
                evidence.append(evidence_record)
                validated_records.append(asdict(evidence_record))
            validated_reviews.append(
                {
                    "selection_id": record.selection_id,
                    "full_text_sha256": fulltext["pdf_sha256"],
                    "markdown_sha256": fulltext["markdown_sha256"],
                    "review_status": status,
                    "summary": summary,
                    **review_metadata(decision),
                    "records": validated_records,
                }
            )

        atomic_write_bytes(
            reviewed_path,
            b"".join(
                json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n"
                for row in validated_reviews
            ),
        )
        pending_path = destination / "pending-evidence-review.csv"
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=["selection_id", "title", "reason"])
        writer.writeheader()
        writer.writerows(pending_rows)
        atomic_write_bytes(pending_path, buffer.getvalue().encode("utf-8-sig"))
        status = "complete" if not pending_rows else "evidence_required"
        reports = ResearchDelivery(destination / "reports").write(
            brief=run["brief"],
            plan=ResearchPlanner().build(run["brief"]),
            candidates=[_candidate(record) for record in selection.records],
            evidence=evidence,
            pending_paper_ids=[row["selection_id"] for row in pending_rows],
            review_status_by_paper={
                row["selection_id"]: row["review_status"]
                for row in validated_reviews
            },
            run_status=status,
        )
        manifest_path = destination / "research-evidence.json"
        write_json(
            manifest_path,
            {
                "schema_version": 1,
                "phase": "evidence",
                "status": status,
                "candidate_snapshot_sha256": run["candidates_sha256"],
                "selection_sha256": selection.manifest["selected_sha256"],
                "full_text_sha256": run["full_text_sha256"],
                "reviewed": len(validated_reviews),
                "pending": len(pending_rows),
                "evidence_records": len(evidence),
                "validated_reviews": reviewed_path.name,
                "pending_reviews": pending_path.name,
                "reports": "reports",
            },
        )
        update_run_manifest(
            destination,
            phase="evidence",
            status=status,
            evidence_manifest=manifest_path.name,
            reports="reports",
        )
        return ResearchEvidenceResult(
            status=status,
            manifest_path=manifest_path,
            reviewed_path=reviewed_path,
            pending_path=pending_path,
            evidence_map=reports.evidence_map,
            nearest_work_matrix=reports.nearest_work_matrix,
            gap_analysis=reports.gap_analysis,
            claim_coverage=reports.claim_coverage,
            reviewed=len(validated_reviews),
            pending=len(pending_rows),
            evidence_records=len(evidence),
        )
