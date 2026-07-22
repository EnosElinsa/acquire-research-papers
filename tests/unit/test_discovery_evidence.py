import json
import math
from dataclasses import replace
from pathlib import Path

from acquire_research_papers.discovery.contracts import CandidateMetadata
from acquire_research_papers.discovery.evidence import EvidencePacket, evaluate_prefilter


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


def screening_spec() -> dict:
    return {
        "scope": {
            "topics": {
                "include": [
                    "evolutionary optimization",
                    "evolutionary algorithm",
                    "multiobjective evolutionary optimization",
                    "surrogate-assisted evolutionary optimization",
                    "quality diversity",
                    "neuroevolution",
                    "population-based training",
                    "genetic programming",
                    "large language model multi-agent",
                    "multi-agent collaboration",
                    "algorithm configuration",
                    "automated algorithm design",
                ],
                "synonyms": [
                    "CMA-ES",
                    "MOEA",
                    "Pareto optimization",
                    "quality-diversity",
                    "LLM-guided search",
                    "multi-agent system",
                    "agent negotiation",
                ],
                "exclude": [
                    "medical",
                    "clinical",
                    "tumor",
                    "cancer",
                    "demo",
                    "autonomous driving",
                ],
            }
        }
    }


def test_prefilter_handles_inflections_hyphens_and_unicode_separators() -> None:
    item = candidate(
        title="Surrogate–Assisted Multi-Objective Evolutionary Algorithms",
        abstract="The optimizers collaborate across populations.",
        keywords=("quality–diversity",),
    )

    result = evaluate_prefilter(item, screening_spec())

    assert result.likely_relevant
    assert "title:surrogate-assisted evolutionary optimization" in result.signals
    assert "keywords:quality diversity" in result.signals


def test_prefilter_uses_title_abstract_and_optional_keywords() -> None:
    title_match = evaluate_prefilter(
        candidate(title="A Multi-Agent System for Planning", abstract="General planning."),
        screening_spec(),
    )
    abstract_match = evaluate_prefilter(
        candidate(
            title="Planning with Language Models",
            abstract="We study multi agent systems that negotiate tasks.",
        ),
        screening_spec(),
    )
    keyword_match = evaluate_prefilter(
        candidate(
            title="Planning with Language Models",
            abstract="General planning.",
            keywords=("agent negotiations",),
        ),
        screening_spec(),
    )

    assert title_match.likely_relevant
    assert abstract_match.likely_relevant
    assert keyword_match.likely_relevant
    assert title_match.signals[0].startswith("title:")
    assert abstract_match.signals[0].startswith("abstract:")
    assert keyword_match.signals[0].startswith("keywords:")


def test_explicit_exclusion_overrides_positive_prefilter_signal() -> None:
    result = evaluate_prefilter(
        candidate(
            title="Multi-Agent Systems for Autonomous Driving",
            abstract="Agents collaborate in traffic.",
        ),
        screening_spec(),
    )

    assert not result.likely_relevant
    assert result.exclusion_signals == ("title:autonomous driving",)
    assert any(signal.startswith("title:multi-agent system") for signal in result.signals)


def test_labeled_prefilter_fixture_meets_precision_and_recall_floor() -> None:
    fixture = Path(__file__).parents[1] / "fixtures" / "discovery" / "screening-labeled.json"
    records = json.loads(fixture.read_text(encoding="utf-8"))
    true_positive = false_positive = false_negative = 0
    for index, record in enumerate(records):
        item = candidate(
            key=f"fixture-{index}",
            title=record["title"],
            abstract=record.get("abstract", ""),
            keywords=tuple(record.get("keywords", ())),
        )
        predicted = evaluate_prefilter(item, screening_spec()).likely_relevant
        expected = bool(record["relevant"])
        true_positive += int(predicted and expected)
        false_positive += int(predicted and not expected)
        false_negative += int(not predicted and expected)

    precision = true_positive / (true_positive + false_positive)
    recall = true_positive / (true_positive + false_negative)
    assert math.isclose(precision, 1.0)
    assert precision >= 0.95
    assert recall >= 0.90
