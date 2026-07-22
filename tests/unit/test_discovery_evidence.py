from dataclasses import replace

from acquire_research_papers.discovery.contracts import CandidateMetadata
from acquire_research_papers.discovery.evidence import EvidencePacket


def candidate(**changes) -> CandidateMetadata:
    base = CandidateMetadata(
        key="provider-key",
        title="Adaptive Edge Resource Allocation",
        year=2025,
        venue="IEEE Transactions on Cybernetics",
        relevance_score=0.0,
        hard_gates_passed=True,
        evidence_fields=("title", "abstract", "keywords", "venue"),
        doi="10.1109/tcyb.2025.1234567",
        official_url="https://doi.org/10.1109/tcyb.2025.1234567",
        abstract="We optimize resources for edge systems.",
        keywords=("edge computing", "resource allocation"),
        publication_type="journal-article",
        track="regular",
        citation_count=17,
        provenance={"source": "crossref", "request_id": "runtime-one"},
        field_provenance={
            "title": ("crossref",),
            "abstract": ("semantic-scholar",),
        },
    )
    return replace(base, **changes)


def test_evidence_packet_has_stable_identity_provenance_and_hash() -> None:
    packet = EvidencePacket.from_candidate(
        candidate(),
        prefilter_signals=("abstract:resource-allocation", "title:edge"),
    )

    assert packet.candidate_id == "doi:10.1109/tcyb.2025.1234567"
    assert packet.metadata_state == "ready"
    assert packet.prefilter_signals == (
        "abstract:resource-allocation",
        "title:edge",
    )
    assert packet.field_provenance["abstract"] == ("semantic-scholar",)
    assert packet.field_provenance["keywords"] == ("crossref",)
    assert len(packet.evidence_hash) == 64
    assert packet.to_dict()["evidence_hash"] == packet.evidence_hash


def test_evidence_hash_changes_only_for_review_evidence() -> None:
    original = EvidencePacket.from_candidate(candidate())

    review_changes = (
        {"title": "Changed title"},
        {"abstract": "Changed abstract"},
        {"keywords": ("different",)},
        {"venue": "Different Venue"},
        {"year": 2024},
        {"publication_type": "proceedings-article"},
    )
    for changes in review_changes:
        changed = EvidencePacket.from_candidate(candidate(**changes))
        assert changed.evidence_hash != original.evidence_hash

    runtime_only = EvidencePacket.from_candidate(
        candidate(
            citation_count=99,
            provenance={"source": "crossref", "request_id": "runtime-two"},
        )
    )
    assert runtime_only.evidence_hash == original.evidence_hash


def test_evidence_metadata_state_requires_title_and_abstract_not_keywords() -> None:
    without_keywords = EvidencePacket.from_candidate(
        candidate(
            keywords=(),
            evidence_fields=("title", "abstract", "venue"),
        )
    )
    without_abstract = EvidencePacket.from_candidate(
        candidate(
            abstract="",
            evidence_fields=("title", "venue"),
        )
    )
    without_title = EvidencePacket.from_candidate(
        candidate(
            title="",
            evidence_fields=("abstract", "venue"),
        )
    )

    assert without_keywords.metadata_state == "ready"
    assert without_abstract.metadata_state == "pending_abstract"
    assert without_title.metadata_state == "missing_title"
