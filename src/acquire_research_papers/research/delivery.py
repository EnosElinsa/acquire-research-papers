from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from acquire_research_papers.artifacts import atomic_write_bytes
from acquire_research_papers.discovery.corpus import CandidateMetadata
from acquire_research_papers.research.evidence import EvidenceRecord
from acquire_research_papers.research.planner import ResearchPlan


@dataclass(frozen=True)
class ResearchDeliveryResult:
    manifest: Path
    pending_review: Path
    evidence_map: Path
    nearest_work_matrix: Path
    gap_analysis: Path
    research_plan: Path


def _write(path: Path, value: str, *, bom: bool = False) -> None:
    encoding = "utf-8-sig" if bom else "utf-8"
    atomic_write_bytes(path, value.encode(encoding))


class ResearchDelivery:
    def __init__(self, output: Path) -> None:
        self.output = output.resolve()

    def write(
        self,
        *,
        brief: dict[str, Any],
        plan: ResearchPlan,
        candidates: list[CandidateMetadata],
        evidence: list[EvidenceRecord],
    ) -> ResearchDeliveryResult:
        self.output.mkdir(parents=True, exist_ok=True)

        manifest = self.output / "research-manifest.csv"
        manifest_buffer = io.StringIO(newline="")
        manifest_writer = csv.writer(manifest_buffer)
        manifest_writer.writerow(
            ["paper_id", "title", "year", "venue", "relevance_score", "review_status"]
        )
        for candidate in candidates:
            manifest_writer.writerow(
                [
                    candidate.key,
                    candidate.title,
                    candidate.year,
                    candidate.venue,
                    f"{candidate.relevance_score:.4f}",
                    "pending_full_text_review",
                ]
            )
        _write(manifest, manifest_buffer.getvalue(), bom=True)

        pending = self.output / "pending-review.csv"
        pending_buffer = io.StringIO(newline="")
        pending_writer = csv.writer(pending_buffer)
        pending_writer.writerow(["paper_id", "title", "reason"])
        for candidate in candidates:
            pending_writer.writerow(
                [candidate.key, candidate.title, "confirm relevance and full-text evidence"]
            )
        _write(pending, pending_buffer.getvalue(), bom=True)

        evidence_map = self.output / "evidence-map.md"
        evidence_lines = ["# Evidence Map", ""]
        if not evidence:
            evidence_lines.extend(
                ["No claim-level evidence has been validated yet.", "", "Abstract matches remain leads only."]
            )
        for record in evidence:
            location = record.section or (f"page {record.page}" if record.page else "no location")
            evidence_lines.extend(
                [
                    f"## {record.claim_id} — {record.paper_id}",
                    "",
                    f"- Relation: `{record.relation}`",
                    f"- Read scope: `{record.read_scope}`",
                    f"- Location: {location}",
                    f"- Explanation: {record.explanation}",
                    f"- Short excerpt: {record.excerpt or '(none)'}",
                    "",
                ]
            )
        _write(evidence_map, "\n".join(evidence_lines).rstrip() + "\n")

        matrix = self.output / "nearest-work-matrix.csv"
        matrix_buffer = io.StringIO(newline="")
        matrix_writer = csv.writer(matrix_buffer)
        matrix_writer.writerow(
            [
                "paper_id",
                "title",
                "year",
                "venue",
                "relevance_score",
                "evidence_relations",
                "max_read_scope",
            ]
        )
        for candidate in candidates:
            records = [record for record in evidence if record.paper_id == candidate.key]
            relations = ";".join(sorted({record.relation for record in records}))
            scope = "full-text" if any(record.read_scope == "full-text" for record in records) else "lead-only"
            matrix_writer.writerow(
                [
                    candidate.key,
                    candidate.title,
                    candidate.year,
                    candidate.venue,
                    f"{candidate.relevance_score:.4f}",
                    relations,
                    scope,
                ]
            )
        _write(matrix, matrix_buffer.getvalue(), bom=True)

        research_plan = self.output / "research-plan.json"
        _write(
            research_plan,
            json.dumps(plan.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )

        gap = self.output / "gap-analysis.md"
        gap_lines = [
            "# Gap Analysis Evidence Report",
            "",
            f"Research question: {brief['research_question']}",
            "",
            "## Scope",
            "",
            "```json",
            json.dumps(brief.get("scope", {}), ensure_ascii=False, indent=2, sort_keys=True),
            "```",
            "",
            "## Search passes",
            "",
        ]
        gap_lines.extend(f"- `{query.kind}`: {query.query}" for query in plan.queries)
        counterexamples = [
            record for record in evidence if record.relation in {"contradicts", "qualifies"}
        ]
        gap_lines.extend(["", "## Closest counterexamples and qualifiers", ""])
        if counterexamples:
            gap_lines.extend(
                f"- {record.paper_id}: {record.relation} — {record.explanation}"
                for record in counterexamples
            )
        else:
            gap_lines.append("- None has been validated from full text yet.")
        gap_lines.extend(
            [
                "",
                "## Bounded conclusion",
                "",
                "No novelty conclusion is asserted until the closest candidates have been checked in full text. "
                "Any later conclusion applies only within the searched scope.",
                "",
            ]
        )
        _write(gap, "\n".join(gap_lines))

        return ResearchDeliveryResult(
            manifest=manifest,
            pending_review=pending,
            evidence_map=evidence_map,
            nearest_work_matrix=matrix,
            gap_analysis=gap,
            research_plan=research_plan,
        )
