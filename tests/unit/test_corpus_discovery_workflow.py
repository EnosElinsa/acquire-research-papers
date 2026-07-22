from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from acquire_research_papers.discovery.contracts import (
    CandidateMetadata,
    CoverageSlice,
    DiscoveryBatch,
    DiscoveryDiagnostic,
    DiscoveryRequest,
)
from acquire_research_papers.discovery.corpus import CorpusDiscoveryWorkflow


def spec() -> dict:
    return {
        "mode": "corpus",
        "name": "evidence-run",
        "target": {"minimum": 1, "preferred": 2, "maximum": 3},
        "scope": {
            "venues": [{"name": "Venue A"}, {"name": "Venue B"}],
            "years": {"include": [2025]},
            "publication_types": {"include": ["journal-article"]},
            "topics": {"include": ["evolutionary algorithm"]},
        },
        "delivery": {
            "profile": "numbered",
            "naming_template": "{number}.{ext}",
            "require_pdf": True,
            "require_official_bibtex": True,
        },
    }


def candidate(
    key: str,
    venue: str,
    *,
    abstract: str = "We study evolutionary algorithms for difficult search problems.",
    provenance: dict | None = None,
) -> CandidateMetadata:
    evidence = ["title", "venue"]
    if abstract:
        evidence.append("abstract")
    return CandidateMetadata(
        key=key,
        title=f"Evolutionary Algorithm {key}",
        year=2025,
        venue=venue,
        relevance_score=0.0,
        hard_gates_passed=True,
        evidence_fields=tuple(evidence),
        doi=f"10.1000/{key}",
        abstract=abstract,
        publication_type="journal-article",
        provenance=provenance or {"source": "fake"},
    )


@dataclass
class StaticDiscoverer:
    calls: int = 0

    def __call__(self, request: DiscoveryRequest) -> DiscoveryBatch:
        self.calls += 1
        return DiscoveryBatch(
            candidates=(
                candidate("ready", "Venue A"),
                candidate("missing", "Venue B", abstract=""),
            ),
            coverage=(
                CoverageSlice("fake", "Venue A", 2025, "complete", 1, 1),
                CoverageSlice("fake", "Venue B", 2025, "complete", 1, 1),
            ),
        )


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_discovery_writes_evidence_artifacts_without_freezing_selection(
    tmp_path: Path,
) -> None:
    result = CorpusDiscoveryWorkflow(discoverer=StaticDiscoverer()).run(spec(), tmp_path)

    assert result.status == "metadata_pending"
    assert result.reviewable == 1
    assert result.pending_metadata == 1
    expected = {
        "request-spec.json",
        "coverage.jsonl",
        "candidates.jsonl",
        "evidence-packets.jsonl",
        "pending-metadata.csv",
        "discovery-errors.jsonl",
        "discovery-manifest.json",
    }
    assert expected.issubset(path.name for path in tmp_path.iterdir())
    assert not (tmp_path / "selected-papers.jsonl").exists()
    assert not (tmp_path / "selection-manifest.json").exists()

    packets = read_jsonl(result.evidence_path)
    assert [packet["candidate_id"] for packet in packets] == [
        "doi:10.1000/missing",
        "doi:10.1000/ready",
    ]
    assert {packet["metadata_state"] for packet in packets} == {
        "pending_abstract",
        "ready",
    }
    assert all(len(packet["evidence_hash"]) == 64 for packet in packets)
    assert read_jsonl(result.coverage_path)[0]["state"] == "complete"
    assert "10.1000/missing" in result.pending_metadata_path.read_text(
        encoding="utf-8-sig"
    )


def test_complete_discovery_rerun_is_idempotent_and_keeps_evidence_hashes(
    tmp_path: Path,
) -> None:
    discoverer = StaticDiscoverer()
    workflow = CorpusDiscoveryWorkflow(discoverer=discoverer)

    first = workflow.run(spec(), tmp_path)
    hashes_before = [row["evidence_hash"] for row in read_jsonl(first.evidence_path)]
    second = workflow.run(spec(), tmp_path)
    hashes_after = [row["evidence_hash"] for row in read_jsonl(second.evidence_path)]

    assert discoverer.calls == 1
    assert hashes_after == hashes_before


def test_partial_discovery_resume_passes_completed_slice_checkpoints(
    tmp_path: Path,
) -> None:
    calls: list[frozenset[str]] = []

    def discover(request: DiscoveryRequest) -> DiscoveryBatch:
        calls.append(request.completed_slices)
        if len(calls) == 1:
            return DiscoveryBatch(
                candidates=(candidate("a", "Venue A"), candidate("b1", "Venue B")),
                coverage=(
                    CoverageSlice("fake", "Venue A", 2025, "complete", 1, 1),
                    CoverageSlice(
                        "fake",
                        "Venue B",
                        2025,
                        "partial",
                        1,
                        1,
                        "next",
                        "network_transient",
                    ),
                ),
            )
        assert "fake:Venue A:2025" in request.completed_slices
        return DiscoveryBatch(
            candidates=(candidate("b2", "Venue B"),),
            coverage=(CoverageSlice("fake", "Venue B", 2025, "complete", 2, 2),),
        )

    workflow = CorpusDiscoveryWorkflow(discoverer=discover)
    first = workflow.run(spec(), tmp_path)
    second = workflow.run(spec(), tmp_path)

    assert first.status == "coverage_incomplete"
    assert second.status == "review_required"
    assert len(calls) == 2
    assert len(read_jsonl(second.candidates_path)) == 3
    coverage = read_jsonl(second.coverage_path)
    assert {(row["venue"], row["state"]) for row in coverage} == {
        ("Venue A", "complete"),
        ("Venue B", "complete"),
    }


def test_resume_retries_legacy_checkpoint_with_retryable_provider_error(
    tmp_path: Path,
) -> None:
    calls: list[frozenset[str]] = []

    def discover(request: DiscoveryRequest) -> DiscoveryBatch:
        calls.append(request.completed_slices)
        if len(calls) == 1:
            return DiscoveryBatch(
                candidates=(candidate("a", "Venue A"),),
                diagnostics=(
                    DiscoveryDiagnostic(
                        "semantic-scholar",
                        "doi-enrichment",
                        "network_transient",
                        "temporarily unavailable",
                        retryable=True,
                    ),
                ),
                covered_slices=("semantic-scholar:doi-batch",),
                coverage=(
                    CoverageSlice(
                        "fake",
                        "Venue A",
                        2025,
                        "partial",
                        1,
                        1,
                        diagnostic_code="network_transient",
                    ),
                ),
            )
        assert "semantic-scholar:doi-batch" not in request.completed_slices
        return DiscoveryBatch(
            covered_slices=("semantic-scholar:doi-batch",),
            coverage=(CoverageSlice("fake", "Venue A", 2025, "complete", 2, 1),),
        )

    workflow = CorpusDiscoveryWorkflow(discoverer=discover)
    workflow.run(spec(), tmp_path)
    second = workflow.run(spec(), tmp_path)

    assert len(calls) == 2
    assert "semantic-scholar:doi-batch" in json.loads(
        second.manifest_path.read_text(encoding="utf-8")
    )["provider_coverage"]


def test_discovery_artifacts_strip_sensitive_keys_and_signed_query_strings(
    tmp_path: Path,
) -> None:
    signed = (
        "https://objects.example/paper.pdf?OSSAccessKeyId=secret&Signature=signed"
        "&token=private"
    )
    unsafe = candidate(
        "unsafe",
        "Venue A",
        provenance={
            "source": "fake",
            "query_url": signed,
            "token": "private",
            "nested": {"Signature": "signed"},
        },
    )
    workflow = CorpusDiscoveryWorkflow(
        discoverer=lambda _: DiscoveryBatch(
            candidates=(unsafe,),
            coverage=(CoverageSlice("fake", "Venue A", 2025, "complete", 1, 1),),
        )
    )

    workflow.run(
        {
            **spec(),
            "scope": {
                **spec()["scope"],
                "venues": [{"name": "Venue A"}],
            },
        },
        tmp_path,
    )

    artifact_text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in tmp_path.iterdir()
        if path.is_file()
    )
    for secret in ("private", "signed", "OSSAccessKeyId", "Signature", "token="):
        assert secret not in artifact_text
    assert "https://objects.example/paper.pdf" in artifact_text
