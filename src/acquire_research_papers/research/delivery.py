from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from acquire_research_papers.artifacts import atomic_write_bytes, sha256_bytes
from acquire_research_papers.discovery.corpus import CandidateMetadata
from acquire_research_papers.research.evidence import EvidenceRecord
from acquire_research_papers.research.planner import ResearchPlan
from acquire_research_papers.research.state import (
    canonical_json,
    claim_ids,
    encode_packets,
)


@dataclass(frozen=True)
class ResearchDeliveryResult:
    manifest: Path
    pending_review: Path
    evidence_map: Path
    nearest_work_matrix: Path
    gap_analysis: Path
    research_plan: Path
    candidates_snapshot: Path
    citation_graph: Path
    run_manifest: Path
    claim_coverage: Path


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
        graph_edges: list[Any] | tuple[Any, ...] = (),
        graph_diagnostics: list[Any] | tuple[Any, ...] = (),
        graph_bounds: Any | None = None,
        pending_paper_ids: list[str] | tuple[str, ...] = (),
        review_status_by_paper: Mapping[str, str] | None = None,
        run_status: str = "review_required",
    ) -> ResearchDeliveryResult:
        self.output.mkdir(parents=True, exist_ok=True)
        run_manifest = self.output / "research-run.json"
        if run_status == "review_required" and run_manifest.exists():
            raise ValueError(
                "output already contains an immutable research run; use a new directory"
            )

        manifest = self.output / "research-manifest.csv"
        manifest_buffer = io.StringIO(newline="")
        manifest_writer = csv.writer(manifest_buffer)
        manifest_writer.writerow(
            ["paper_id", "title", "year", "venue", "relevance_score", "review_status"]
        )
        paper_statuses = review_status_by_paper or {}
        for candidate in candidates:
            manifest_writer.writerow(
                [
                    candidate.key,
                    candidate.title,
                    candidate.year,
                    candidate.venue,
                    f"{candidate.relevance_score:.4f}",
                    paper_statuses.get(candidate.key, "pending_full_text_review"),
                ]
            )
        _write(manifest, manifest_buffer.getvalue(), bom=True)

        pending = self.output / "pending-review.csv"
        pending_buffer = io.StringIO(newline="")
        pending_writer = csv.writer(pending_buffer)
        pending_writer.writerow(["paper_id", "title", "reason"])
        for candidate in candidates:
            if candidate.key in paper_statuses:
                continue
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

        coverage_path = self.output / "claim-coverage.csv"
        coverage_buffer = io.StringIO(newline="")
        coverage_writer = csv.writer(coverage_buffer)
        coverage_writer.writerow(
            [
                "claim_id",
                "claim_text",
                "required_relation",
                "evidence_count",
                "relations",
                "papers",
                "status",
            ]
        )
        claim_texts: dict[str, str] = {"research-question": str(brief["research_question"])}
        required_relations: dict[str, str] = {}
        for index, claim in enumerate(brief.get("claims") or (), start=1):
            if isinstance(claim, str):
                claim_texts[f"claim-{index}"] = claim
            elif isinstance(claim, dict):
                claim_id = str(claim.get("id") or "")
                claim_texts[claim_id] = str(claim.get("text") or "")
                required_relation = str(claim.get("required_relation") or "")
                if required_relation:
                    required_relations[claim_id] = required_relation
        for claim_id in claim_ids(brief):
            records = [record for record in evidence if record.claim_id == claim_id]
            required_relation = required_relations.get(claim_id, "")
            relation_satisfied = not required_relation or any(
                record.relation == required_relation for record in records
            )
            coverage_writer.writerow(
                [
                    claim_id,
                    claim_texts.get(claim_id, ""),
                    required_relation,
                    len(records),
                    ";".join(sorted({record.relation for record in records})),
                    ";".join(sorted({record.paper_id for record in records})),
                    "covered" if records and relation_satisfied else "unresolved",
                ]
            )
        _write(coverage_path, coverage_buffer.getvalue(), bom=True)

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
        gap_lines.extend(["", "## Claim coverage", ""])
        for claim_id in claim_ids(brief):
            records = [record for record in evidence if record.claim_id == claim_id]
            required_relation = required_relations.get(claim_id, "")
            matching = [
                record
                for record in records
                if not required_relation or record.relation == required_relation
            ]
            if matching:
                relations = ", ".join(sorted({record.relation for record in records}))
                gap_lines.append(f"- `{claim_id}`: {len(records)} record(s); {relations}.")
            else:
                requirement = (
                    f"; required relation `{required_relation}` was not found"
                    if required_relation
                    else ""
                )
                gap_lines.append(
                    f"- `{claim_id}`: unresolved in the reviewed evidence{requirement}."
                )
        gap_lines.extend(["", "## Pending full-text work", ""])
        if pending_paper_ids:
            gap_lines.extend(f"- `{paper_id}`" for paper_id in pending_paper_ids)
        else:
            gap_lines.append("- None in the frozen closest-paper set.")
        gap_lines.extend(
            [
                "",
                "## Bounded conclusion",
                "",
                (
                    "The frozen closest-paper set has been reviewed, but absent evidence is not proof of universal novelty. "
                    "The conclusion remains bounded within the searched scope."
                    if run_status == "complete"
                    else "No novelty conclusion is asserted until the closest candidates have been checked in full text. "
                    "Any later conclusion applies only within the searched scope."
                ),
                "",
            ]
        )
        _write(gap, "\n".join(gap_lines))

        candidates_snapshot = self.output / "research-candidates.jsonl"
        candidate_bytes = encode_packets(candidates)
        atomic_write_bytes(candidates_snapshot, candidate_bytes)

        def serializable(value: Any) -> Any:
            return asdict(value) if hasattr(value, "__dataclass_fields__") else value

        citation_graph = self.output / "citation-graph.json"
        _write(
            citation_graph,
            json.dumps(
                {
                    "schema_version": 1,
                    "bounds": serializable(graph_bounds) if graph_bounds else None,
                    "edges": [serializable(edge) for edge in graph_edges],
                    "diagnostics": [serializable(item) for item in graph_diagnostics],
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
        )
        _write(
            run_manifest,
            json.dumps(
                {
                    "schema_version": 1,
                    "phase": "discovery",
                    "status": run_status,
                    "brief": brief,
                    "brief_sha256": sha256_bytes(canonical_json(brief)),
                    "candidate_count": len(candidates),
                    "candidates_file": candidates_snapshot.name,
                    "candidates_sha256": sha256_bytes(candidate_bytes),
                    "citation_graph": citation_graph.name,
                    "research_plan": research_plan.name,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
        )

        return ResearchDeliveryResult(
            manifest=manifest,
            pending_review=pending,
            evidence_map=evidence_map,
            nearest_work_matrix=matrix,
            gap_analysis=gap,
            research_plan=research_plan,
            candidates_snapshot=candidates_snapshot,
            citation_graph=citation_graph,
            run_manifest=run_manifest,
            claim_coverage=coverage_path,
        )
