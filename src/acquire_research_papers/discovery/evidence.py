from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass

from acquire_research_papers.discovery.contracts import CandidateMetadata
from acquire_research_papers.discovery.coordinator import candidate_identity


_DASHES = re.compile(r"[\u2010-\u2015\u2212]")
_COMPOUNDS = {
    "multiagent": ("multi", "agent"),
    "multiobjective": ("multi", "objective"),
    "multitask": ("multi", "task"),
    "neuroevolution": ("neuro", "evolution"),
}
_STEM_PREFIXES = (
    (("evolutionary", "evolution"), "evol"),
    (("optimization", "optimisation", "optimizer", "optimiser", "optimize", "optimise"), "search"),
    (("algorithm",), "search"),
    (("collaboration", "collaborative", "collaborate"), "collabor"),
    (("communication", "communicate"), "communic"),
    (("configuration", "configure"), "configur"),
    (("negotiation", "negotiate"), "negoti"),
    (("programming", "program"), "program"),
    (("training", "train"), "train"),
    (("assisted", "assist"), "assist"),
    (("automated", "automatic"), "automat"),
    (("guided", "guide"), "guid"),
    (("genetic",), "genet"),
)


def _display_term(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = _DASHES.sub("-", normalized)
    return " ".join(normalized.split())


def _stem_token(token: str) -> str:
    for prefixes, stem in _STEM_PREFIXES:
        if any(token == prefix or token.startswith(f"{prefix}s") for prefix in prefixes):
            return stem
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("s") and len(token) > 3 and not token.endswith("ss"):
        return token[:-1]
    return token


def _tokens(value: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = _DASHES.sub("-", normalized)
    raw = re.findall(r"[^\W_]+", normalized, flags=re.UNICODE)
    expanded: list[str] = []
    for token in raw:
        expanded.extend(_COMPOUNDS.get(token, (token,)))
    return tuple(_stem_token(token) for token in expanded)


def _ordered_phrase_match(haystack: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    if not needle or len(haystack) < len(needle):
        return False
    maximum_window = len(needle) + min(3, max(0, len(needle) - 1))
    for start, token in enumerate(haystack):
        if token != needle[0]:
            continue
        matched = 1
        end = min(len(haystack), start + maximum_window)
        for current in haystack[start + 1 : end]:
            if matched < len(needle) and current == needle[matched]:
                matched += 1
        if matched == len(needle):
            return True
    return False


@dataclass(frozen=True)
class PrefilterResult:
    likely_relevant: bool
    signals: tuple[str, ...]
    exclusion_signals: tuple[str, ...]


def evaluate_prefilter(candidate: CandidateMetadata, spec: dict[str, object]) -> PrefilterResult:
    scope = spec.get("scope", {})
    assert isinstance(scope, dict)
    topics = scope.get("topics", {})
    assert isinstance(topics, dict)
    positive_terms = tuple(
        str(value)
        for value in (*topics.get("include", ()), *topics.get("synonyms", ()))
        if str(value).strip()
    )
    exclusion_terms = tuple(
        str(value) for value in topics.get("exclude", ()) if str(value).strip()
    )
    fields = (
        ("title", candidate.title),
        ("abstract", candidate.abstract),
        ("keywords", " ".join(candidate.keywords)),
    )
    field_tokens = {field: _tokens(value) for field, value in fields}

    signals: list[str] = []
    for field, _ in fields:
        for term in positive_terms:
            if _ordered_phrase_match(field_tokens[field], _tokens(term)):
                signals.append(f"{field}:{_display_term(term)}")

    exclusions: list[str] = []
    for field, _ in fields:
        for term in exclusion_terms:
            if _ordered_phrase_match(field_tokens[field], _tokens(term)):
                exclusions.append(f"{field}:{_display_term(term)}")

    return PrefilterResult(
        likely_relevant=bool(signals or not positive_terms) and not exclusions,
        signals=tuple(dict.fromkeys(signals)),
        exclusion_signals=tuple(dict.fromkeys(exclusions)),
    )


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

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> EvidencePacket:
        values = dict(payload)
        for field in ("keywords", "prefilter_signals", "evidence_fields"):
            values[field] = tuple(values.get(field, ()))
        values["field_provenance"] = {
            str(field): tuple(sources)
            for field, sources in dict(values.get("field_provenance", {})).items()
        }
        try:
            return cls(**values)
        except TypeError as exc:
            raise ValueError("evidence packet does not match schema version 1") from exc
