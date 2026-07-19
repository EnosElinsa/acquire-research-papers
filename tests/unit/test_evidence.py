from pathlib import Path

import pytest

from acquire_research_papers.registry import Registry
from acquire_research_papers.research.evidence import EvidenceRecord, EvidenceValidationError


def test_abstract_only_evidence_cannot_be_direct_support() -> None:
    with pytest.raises(EvidenceValidationError, match="full text"):
        EvidenceRecord(
            claim_id="claim-1",
            paper_id="paper-1",
            relation="direct-support",
            read_scope="abstract-only",
            section=None,
            page=None,
            excerpt="",
            explanation="The abstract appears relevant.",
        ).validate()


def test_full_text_direct_support_requires_location_and_excerpt() -> None:
    with pytest.raises(EvidenceValidationError, match="section or page"):
        EvidenceRecord(
            claim_id="claim-1",
            paper_id="paper-1",
            relation="direct-support",
            read_scope="full-text",
            section=None,
            page=None,
            excerpt="A short exact excerpt.",
            explanation="This directly defines the mechanism.",
        ).validate()


def test_background_evidence_may_be_abstract_only() -> None:
    record = EvidenceRecord(
        claim_id="claim-1",
        paper_id="paper-1",
        relation="background",
        read_scope="abstract-only",
        section=None,
        page=None,
        excerpt="",
        explanation="The abstract establishes broad context.",
    )
    assert record.validate() is record


def test_evidence_record_persists_in_global_registry(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "registry.sqlite")
    paper_id = registry.create_verified_paper("Paper", "10.1234/evidence")
    record = EvidenceRecord(
        claim_id="claim-1",
        paper_id=paper_id,
        relation="qualifies",
        read_scope="full-text",
        section="Limitations",
        page=9,
        excerpt="The method assumes a static environment.",
        explanation="The assumption narrows the claim.",
    ).validate()
    registry.add_evidence("research-task", record.to_dict())
    stored = registry.evidence_for_task("research-task")
    assert stored[0]["claim_id"] == "claim-1"
    assert stored[0]["relation"] == "qualifies"
