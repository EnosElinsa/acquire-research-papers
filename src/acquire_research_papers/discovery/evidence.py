from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from acquire_research_papers.discovery.contracts import CandidateMetadata
from acquire_research_papers.discovery.coordinator import candidate_identity


def _metadata_state(candidate: CandidateMetadata) -> str:
    if not candidate.title.strip():
        return "missing_title"
    if not candidate.abstract.strip():
        return "pending_abstract"
    return "ready"


def _field_provenance(candidate: CandidateMetadata) -> dict[str, tuple[str, ...]]:
    provenance = {
        field: tuple(dict.fromkeys(sources))
        for field, sources in candidate.field_provenance.items()
    }
    source = str(candidate.provenance.get("source", "")).strip()
    if source:
        for field in candidate.evidence_fields:
            provenance.setdefault(field, (source,))
    return dict(sorted(provenance.items()))


@dataclass(frozen=True)
class EvidencePacket:
    candidate_id: str
    evidence_hash: str
    candidate_key: str
    doi: str | None
    official_url: str | None
    title: str
    abstract: str
    keywords: tuple[str, ...]
    venue: str
    year: int
    publication_type: str | None
    track: str | None
    metadata_state: str
    hard_gates_passed: bool
    prefilter_signals: tuple[str, ...]
    evidence_fields: tuple[str, ...]
    field_provenance: dict[str, tuple[str, ...]]

    @staticmethod
    def _hash_payload(payload: dict[str, object]) -> str:
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    @classmethod
    def from_candidate(
        cls,
        candidate: CandidateMetadata,
        *,
        prefilter_signals: tuple[str, ...] = (),
    ) -> EvidencePacket:
        candidate_id = candidate_identity(candidate)
        fields = tuple(sorted(dict.fromkeys(candidate.evidence_fields)))
        signals = tuple(sorted(dict.fromkeys(prefilter_signals)))
        provenance = _field_provenance(candidate)
        metadata_state = _metadata_state(candidate)
        review_payload: dict[str, object] = {
            "candidate_id": candidate_id,
            "doi": candidate.doi,
            "official_url": candidate.official_url,
            "title": candidate.title,
            "abstract": candidate.abstract,
            "keywords": candidate.keywords,
            "venue": candidate.venue,
            "year": candidate.year,
            "publication_type": candidate.publication_type,
            "track": candidate.track,
            "metadata_state": metadata_state,
            "hard_gates_passed": candidate.hard_gates_passed,
            "prefilter_signals": signals,
            "evidence_fields": fields,
            "field_provenance": provenance,
        }
        return cls(
            candidate_id=candidate_id,
            evidence_hash=cls._hash_payload(review_payload),
            candidate_key=candidate.key,
            doi=candidate.doi,
            official_url=candidate.official_url,
            title=candidate.title,
            abstract=candidate.abstract,
            keywords=candidate.keywords,
            venue=candidate.venue,
            year=candidate.year,
            publication_type=candidate.publication_type,
            track=candidate.track,
            metadata_state=metadata_state,
            hard_gates_passed=candidate.hard_gates_passed,
            prefilter_signals=signals,
            evidence_fields=fields,
            field_provenance=provenance,
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
