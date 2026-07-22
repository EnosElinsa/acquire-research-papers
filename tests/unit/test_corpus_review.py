from __future__ import annotations

import json
from pathlib import Path

import pytest

from acquire_research_papers.artifacts import sha256_bytes
from acquire_research_papers.discovery.contracts import (
    CandidateMetadata,
    CoverageSlice,
    DiscoveryBatch,
)
from acquire_research_papers.discovery.corpus import CorpusDiscoveryWorkflow
from acquire_research_papers.discovery.review import (
    CorpusReviewWorkflow,
    ReviewValidationError,
)
from acquire_research_papers.selection import SelectionStore


def corpus_spec(*, minimum: int = 2, preferred: int = 2) -> dict:
    return {
        "mode": "corpus",
        "name": "review-test",
        "target": {"minimum": minimum, "preferred": preferred, "maximum": 4},
        "scope": {
            "venues": [
                {"name": "Conference", "kind": "conference", "short_name": "CONF"},
                {"name": "Journal", "kind": "journal", "short_name": "JOUR"},
            ],
            "years": {"include": [2025, 2024], "priority": [2025, 2024]},
            "publication_types": {
                "include": ["proceedings-article", "journal-article"]
            },
            "topics": {"include": ["evolutionary algorithm"]},
        },
        "quotas": {
            "groups": [
                {"name": "conference", "minimum": 1, "venues": ["Conference"]},
                {"name": "journal", "minimum": 1, "venues": ["Journal"]},
            ],
            "recent_window": {"from": "2025-01-01", "minimum_ratio": 0.5},
        },
        "delivery": {"profile": "generic"},
    }


def candidate(
    key: str,
    venue: str,
    *,
    year: int = 2025,
    abstract: str = "We develop an evolutionary algorithm for difficult search.",
) -> CandidateMetadata:
    publication_type = (
        "proceedings-article" if venue == "Conference" else "journal-article"
    )
    evidence = ("title", "abstract", "venue") if abstract else ("title", "venue")
    return CandidateMetadata(
        key=key,
        title=f"Evolutionary Algorithm {key}",
        year=year,
        venue=venue,
        relevance_score=0.0,
        hard_gates_passed=True,
        evidence_fields=evidence,
        doi=f"10.1000/{key}",
        abstract=abstract,
        publication_type=publication_type,
        publication_date=f"{year}-06-01",
        provenance={"source": "fixture"},
    )


def create_run(tmp_path: Path, candidates: tuple[CandidateMetadata, ...], spec: dict) -> Path:
    venues = [item["name"] for item in spec.get("scope", {}).get("venues", ())]
    years = spec.get("scope", {}).get("years", {}).get("include", ())
    coverage = tuple(
        CoverageSlice("fixture", venue, year, "complete", 1, 1)
        for venue in venues
        for year in years
    )
    CorpusDiscoveryWorkflow(
        discoverer=lambda _: DiscoveryBatch(candidates=candidates, coverage=coverage)
    ).run(spec, tmp_path)
    return tmp_path


def packets(run: Path) -> dict[str, dict]:
    return {
        row["candidate_id"]: row
        for row in (
            json.loads(line)
            for line in (run / "evidence-packets.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
        )
    }


def decision(packet: dict, value: str = "accept", **changes) -> dict:
    record = {
        "candidate_id": packet["candidate_id"],
        "evidence_hash": packet["evidence_hash"],
        "decision": value,
        "matched_topics": ["evolutionary algorithm"] if value == "accept" else [],
        "evidence_fields": ["title", "abstract"] if packet["abstract"] else ["title"],
        "reason": "The title and abstract directly address the requested topic.",
        "reviewer": "codex",
        "rule_version": "corpus-semantic-v1",
    }
    record.update(changes)
    return record


def write_decisions(path: Path, records: list[dict]) -> Path:
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    return path


def test_review_import_validates_decisions_and_freezes_schema_one_selection(
    tmp_path: Path,
) -> None:
    run = create_run(
        tmp_path / "run",
        (
            candidate("conference", "Conference"),
            candidate("journal", "Journal"),
            candidate("reject", "Journal", year=2024),
        ),
        corpus_spec(),
    )
    evidence = packets(run)
    decisions = write_decisions(
        tmp_path / "decisions.jsonl",
        [
            decision(evidence["doi:10.1000/conference"]),
            decision(evidence["doi:10.1000/journal"]),
            decision(
                evidence["doi:10.1000/reject"],
                "reject",
                reason="The paper is outside the requested research focus.",
                evidence_fields=["title", "abstract"],
            ),
        ],
    )

    result = CorpusReviewWorkflow().run(run, decisions)

    assert result.status == "frozen"
    assert (result.accepted, result.rejected, result.pending, result.selected) == (2, 1, 0, 2)
    selection = SelectionStore.load(result.selection_manifest_path)
    assert selection.manifest["schema_version"] == 1
    assert {record.venue for record in selection.records} == {"Conference", "Journal"}
    assert result.shortfall_classes == ()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda records: records + [records[0]], "duplicate"),
        (lambda records: [{**records[0], "candidate_id": "doi:unknown"}], "unknown"),
        (lambda records: [{**records[0], "evidence_hash": "0" * 64}], "hash"),
        (lambda records: [{**records[0], "decision": "maybe"}], "decision"),
    ],
)
def test_review_rejects_duplicate_unknown_tampered_and_invalid_records(
    tmp_path: Path,
    mutation,
    message: str,
) -> None:
    run = create_run(
        tmp_path / "run",
        (candidate("one", "Conference"),),
        corpus_spec(minimum=1, preferred=1),
    )
    record = decision(next(iter(packets(run).values())))
    decisions = write_decisions(tmp_path / "decisions.jsonl", mutation([record]))

    with pytest.raises(ReviewValidationError, match=message):
        CorpusReviewWorkflow().run(run, decisions)

    assert not (run / "selected-papers.jsonl").exists()


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"reason": ""}, "reason"),
        ({"matched_topics": []}, "matched_topics"),
        ({"evidence_fields": []}, "evidence_fields"),
        ({"evidence_fields": ["full_text"]}, "evidence_fields"),
        ({"reviewer": "automatic-threshold"}, "reviewer"),
        ({"rule_version": ""}, "rule_version"),
    ],
)
def test_accept_requires_explainable_codex_semantic_evidence(
    tmp_path: Path,
    changes: dict,
    message: str,
) -> None:
    run = create_run(
        tmp_path / "run",
        (candidate("one", "Conference"),),
        corpus_spec(minimum=1, preferred=1),
    )
    record = decision(next(iter(packets(run).values())), **changes)
    decisions = write_decisions(tmp_path / "decisions.jsonl", [record])

    with pytest.raises(ReviewValidationError, match=message):
        CorpusReviewWorkflow().run(run, decisions)


def test_missing_abstract_cannot_be_accepted_and_remains_evidence_shortfall(
    tmp_path: Path,
) -> None:
    run = create_run(
        tmp_path / "run",
        (candidate("missing", "Conference", abstract=""),),
        corpus_spec(minimum=1, preferred=1),
    )
    packet = next(iter(packets(run).values()))
    decisions = write_decisions(tmp_path / "invalid.jsonl", [decision(packet)])

    with pytest.raises(ReviewValidationError, match="metadata"):
        CorpusReviewWorkflow().run(run, decisions)

    empty = write_decisions(tmp_path / "empty.jsonl", [])
    result = CorpusReviewWorkflow().run(run, empty)
    assert result.status == "shortfall"
    assert "evidence" in result.shortfall_classes
    assert result.pending == 1


def test_missing_review_and_quota_constraints_have_named_shortfalls(tmp_path: Path) -> None:
    run = create_run(
        tmp_path / "run",
        (
            candidate("conference", "Conference", year=2024),
            candidate("journal", "Journal", year=2024),
        ),
        corpus_spec(minimum=2, preferred=2),
    )
    evidence = packets(run)
    decisions = write_decisions(
        tmp_path / "decisions.jsonl",
        [decision(evidence["doi:10.1000/conference"])],
    )

    result = CorpusReviewWorkflow().run(run, decisions)

    assert result.status == "shortfall"
    assert set(result.shortfall_classes) == {"review", "quota"}
    assert "group:journal:1" in result.quota_shortfalls
    assert "recent:1" in result.quota_shortfalls


def test_unreviewed_overflow_does_not_block_a_satisfied_selection(tmp_path: Path) -> None:
    run = create_run(
        tmp_path / "run",
        (
            candidate("conference", "Conference"),
            candidate("journal", "Journal"),
            candidate("ready-overflow", "Journal", year=2024),
            candidate("metadata-overflow", "Journal", year=2024, abstract=""),
        ),
        corpus_spec(minimum=2, preferred=2),
    )
    evidence = packets(run)
    decisions = write_decisions(
        tmp_path / "decisions.jsonl",
        [
            decision(evidence["doi:10.1000/conference"]),
            decision(evidence["doi:10.1000/journal"]),
        ],
    )

    result = CorpusReviewWorkflow().run(run, decisions)

    assert result.status == "frozen"
    assert result.selected == 2
    assert result.pending == 2
    assert result.ready_unreviewed == 1
    assert result.review_completion == "target_satisfied_early_stop"
    assert result.shortfall_classes == ()


def test_early_stop_is_not_frozen_before_the_preferred_target(tmp_path: Path) -> None:
    spec = corpus_spec(minimum=1, preferred=2)
    spec.pop("quotas")
    run = create_run(
        tmp_path / "run",
        (
            candidate("accepted", "Conference"),
            candidate("unreviewed", "Journal"),
        ),
        spec,
    )
    evidence = packets(run)
    decisions = write_decisions(
        tmp_path / "decisions.jsonl",
        [decision(evidence["doi:10.1000/accepted"])],
    )

    result = CorpusReviewWorkflow().run(run, decisions)

    assert result.status == "shortfall"
    assert result.review_completion == "incomplete"
    assert result.ready_unreviewed == 1
    assert "review" in result.shortfall_classes


def test_review_import_is_idempotent_but_rejects_conflicting_rewrite(tmp_path: Path) -> None:
    run = create_run(
        tmp_path / "run",
        (candidate("one", "Conference"),),
        corpus_spec(minimum=1, preferred=1),
    )
    packet = next(iter(packets(run).values()))
    decisions = write_decisions(tmp_path / "decisions.jsonl", [decision(packet)])
    workflow = CorpusReviewWorkflow()

    first = workflow.run(run, decisions)
    second = workflow.run(run, decisions)
    assert second.selection_manifest_path == first.selection_manifest_path

    changed = write_decisions(
        tmp_path / "changed.jsonl",
        [decision(packet, "reject", reason="Changed decision")],
    )
    with pytest.raises(ReviewValidationError, match="already frozen"):
        workflow.run(run, changed)


def test_review_rejects_a_request_changed_after_discovery(tmp_path: Path) -> None:
    run = create_run(
        tmp_path / "run",
        (candidate("one", "Conference"),),
        corpus_spec(minimum=1, preferred=1),
    )
    packet = next(iter(packets(run).values()))
    decisions = write_decisions(tmp_path / "decisions.jsonl", [decision(packet)])
    request_path = run / "request-spec.json"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["target"]["maximum"] = 3
    request_path.write_text(json.dumps(request), encoding="utf-8")

    with pytest.raises(ReviewValidationError, match="request hash"):
        CorpusReviewWorkflow().run(run, decisions)


@pytest.mark.parametrize(
    ("artifact", "message"),
    [
        ("candidates.jsonl", "candidates"),
        ("evidence-packets.jsonl", "evidence packets"),
        ("coverage.jsonl", "coverage"),
    ],
)
def test_review_rejects_discovery_artifact_mutation(
    tmp_path: Path,
    artifact: str,
    message: str,
) -> None:
    run = create_run(
        tmp_path / "run",
        (candidate("one", "Conference"),),
        corpus_spec(minimum=1, preferred=1),
    )
    packet = next(iter(packets(run).values()))
    decisions = write_decisions(tmp_path / "decisions.jsonl", [decision(packet)])
    with (run / artifact).open("a", encoding="utf-8") as handle:
        handle.write(" \n")

    with pytest.raises(ReviewValidationError, match=message):
        CorpusReviewWorkflow().run(run, decisions)


def test_cached_review_revalidates_the_frozen_selection(tmp_path: Path) -> None:
    run = create_run(
        tmp_path / "run",
        (candidate("one", "Conference"),),
        corpus_spec(minimum=1, preferred=1),
    )
    packet = next(iter(packets(run).values()))
    decisions = write_decisions(tmp_path / "decisions.jsonl", [decision(packet)])
    workflow = CorpusReviewWorkflow()
    result = workflow.run(run, decisions)
    result.selected_path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ReviewValidationError, match="frozen selection"):
        workflow.run(run, decisions)


def test_cached_review_rejects_selection_and_manifest_rewritten_together(
    tmp_path: Path,
) -> None:
    run = create_run(
        tmp_path / "run",
        (candidate("one", "Conference"),),
        corpus_spec(minimum=1, preferred=1),
    )
    packet = next(iter(packets(run).values()))
    decisions = write_decisions(tmp_path / "decisions.jsonl", [decision(packet)])
    workflow = CorpusReviewWorkflow()
    result = workflow.run(run, decisions)
    replacement = b""
    result.selected_path.write_bytes(replacement)
    selection_manifest = json.loads(
        result.selection_manifest_path.read_text(encoding="utf-8")
    )
    selection_manifest["selected_sha256"] = sha256_bytes(replacement)
    selection_manifest["selected_count"] = 0
    result.selection_manifest_path.write_text(
        json.dumps(selection_manifest), encoding="utf-8"
    )

    with pytest.raises(ReviewValidationError, match="frozen selection"):
        workflow.run(run, decisions)


def test_cached_review_revalidates_review_audit_artifacts(tmp_path: Path) -> None:
    run = create_run(
        tmp_path / "run",
        (candidate("one", "Conference"),),
        corpus_spec(minimum=1, preferred=1),
    )
    packet = next(iter(packets(run).values()))
    decisions = write_decisions(tmp_path / "decisions.jsonl", [decision(packet)])
    workflow = CorpusReviewWorkflow()
    result = workflow.run(run, decisions)
    with result.reviewed_path.open("a", encoding="utf-8") as handle:
        handle.write(" \n")

    with pytest.raises(ReviewValidationError, match="audit artifact"):
        workflow.run(run, decisions)


def test_valid_spec_without_delivery_uses_generic_layout(tmp_path: Path) -> None:
    spec = corpus_spec(minimum=1, preferred=1)
    spec.pop("delivery")
    spec.pop("quotas")
    run = create_run(
        tmp_path / "run",
        (candidate("one", "Conference"),),
        spec,
    )
    packet = next(iter(packets(run).values()))
    decisions = write_decisions(tmp_path / "decisions.jsonl", [decision(packet)])

    result = CorpusReviewWorkflow().run(run, decisions)

    assert result.status == "frozen"
    assert SelectionStore.load(result.selection_manifest_path).records[0].relative_pdf.endswith(
        "/paper.pdf"
    )
