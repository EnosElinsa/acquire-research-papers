from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import replace

from acquire_research_papers.discovery.contracts import (
    CandidateMetadata,
    DiscoveryBatch,
    DiscoveryDiagnostic,
    DiscoveryEnricher,
    DiscoveryProvider,
    DiscoveryRequest,
)
from acquire_research_papers.http import HttpStatusError, NetworkTransient, RateLimited
from acquire_research_papers.models import normalize_doi


class CandidateConflict(ValueError):
    """Two records sharing a discovery identity disagree on a hard identity field."""


_METADATA_SOURCES = frozenset({"crossref", "openalex", "semantic-scholar"})


def _normalized(value: str) -> str:
    return " ".join(re.findall(r"\w+", value.casefold()))


def candidate_identity(candidate: CandidateMetadata) -> str:
    if candidate.doi:
        return f"doi:{normalize_doi(candidate.doi)}"
    if candidate.official_url:
        return f"url:{candidate.official_url.rstrip('/').casefold()}"
    return "meta:" + "|".join(
        (_normalized(candidate.title), str(candidate.year), _normalized(candidate.venue))
    )


def _source(candidate: CandidateMetadata) -> str:
    return str(candidate.provenance.get("source", ""))


def _is_official(candidate: CandidateMetadata) -> bool:
    source = _source(candidate)
    return bool(source and source not in _METADATA_SOURCES)


def _pick(previous: CandidateMetadata, current: CandidateMetadata, field: str):
    old = getattr(previous, field)
    new = getattr(current, field)
    if new and (not old or (_is_official(current) and not _is_official(previous))):
        return new
    return old


def _field_sources(candidate: CandidateMetadata) -> dict[str, tuple[str, ...]]:
    fields = dict(candidate.field_provenance)
    source = _source(candidate)
    if source:
        for field in candidate.evidence_fields:
            fields.setdefault(field, (source,))
    return fields


def _source_records(candidate: CandidateMetadata) -> tuple[dict[str, object], ...]:
    if candidate.source_records:
        return candidate.source_records
    if candidate.provenance:
        return (dict(candidate.provenance),)
    return ()


def merge_candidates(
    previous: CandidateMetadata | None,
    current: CandidateMetadata,
) -> CandidateMetadata:
    if previous is None:
        return replace(
            current,
            field_provenance=_field_sources(current),
            source_records=_source_records(current),
        )
    if previous.doi and current.doi and normalize_doi(previous.doi) != normalize_doi(current.doi):
        raise CandidateConflict("conflicting DOI")
    same_doi = bool(
        previous.doi
        and current.doi
        and normalize_doi(previous.doi) == normalize_doi(current.doi)
    )
    if previous.year and current.year and previous.year != current.year and not same_doi:
        raise CandidateConflict("conflicting year")

    field_provenance: dict[str, tuple[str, ...]] = {}
    previous_fields = _field_sources(previous)
    current_fields = _field_sources(current)
    for key in previous_fields.keys() | current_fields.keys():
        field_provenance[key] = tuple(
            dict.fromkeys((*previous_fields.get(key, ()), *current_fields.get(key, ())))
        )

    return replace(
        previous,
        key=_pick(previous, current, "key"),
        title=_pick(previous, current, "title"),
        year=int(_pick(previous, current, "year")),
        venue=_pick(previous, current, "venue"),
        doi=_pick(previous, current, "doi"),
        official_url=_pick(previous, current, "official_url"),
        authors=_pick(previous, current, "authors"),
        abstract=_pick(previous, current, "abstract"),
        publication_type=_pick(previous, current, "publication_type"),
        track=_pick(previous, current, "track"),
        publication_date=_pick(previous, current, "publication_date"),
        relevance_score=max(previous.relevance_score, current.relevance_score),
        hard_gates_passed=previous.hard_gates_passed or current.hard_gates_passed,
        evidence_fields=tuple(
            dict.fromkeys((*previous.evidence_fields, *current.evidence_fields))
        ),
        keywords=tuple(dict.fromkeys((*previous.keywords, *current.keywords))),
        related_ids=tuple(dict.fromkeys((*previous.related_ids, *current.related_ids))),
        citation_count=max(previous.citation_count, current.citation_count),
        provenance=(current.provenance if _is_official(current) else previous.provenance),
        field_provenance=field_provenance,
        source_records=(*_source_records(previous), *_source_records(current)),
    )


class DiscoveryCoordinator:
    def __init__(
        self,
        providers: Iterable[DiscoveryProvider],
        *,
        enrichers: Iterable[DiscoveryEnricher] = (),
    ) -> None:
        self.providers = tuple(providers)
        self.enrichers = tuple(enrichers)

    def discover(self, request: DiscoveryRequest) -> DiscoveryBatch:
        merged: dict[str, CandidateMetadata] = {}
        diagnostics: list[DiscoveryDiagnostic] = []
        covered: list[str] = []
        for provider in self.providers:
            capability = provider.capabilities()
            supported_venues = tuple(
                venue for venue in request.venues if capability.supports(venue)
            )
            if request.venues and not supported_venues:
                continue
            supported_years = tuple(
                year for year in request.years if capability.supports_year(year)
            )
            if request.years and not supported_years:
                continue
            provider_request = request.with_scope(
                supported_venues or request.venues,
                supported_years or request.years,
            )
            try:
                batch = provider.discover(provider_request)
            except (RateLimited, NetworkTransient):
                diagnostics.append(
                    DiscoveryDiagnostic(
                        capability.provider_id,
                        "discover",
                        "network_transient",
                        "provider temporarily unavailable",
                        retryable=True,
                    )
                )
                continue
            except (HttpStatusError, RuntimeError, ValueError):
                diagnostics.append(
                    DiscoveryDiagnostic(
                        capability.provider_id,
                        "discover",
                        "provider_error",
                        "provider failed during discovery",
                    )
                )
                continue
            diagnostics.extend(batch.diagnostics)
            covered.extend(batch.covered_slices)
            for candidate in batch.candidates:
                identity = candidate_identity(candidate)
                try:
                    merged[identity] = merge_candidates(merged.get(identity), candidate)
                except CandidateConflict:
                    diagnostics.append(
                        DiscoveryDiagnostic(
                            capability.provider_id,
                            "merge",
                            "identity_conflict",
                            "candidate identity fields conflict",
                        )
                    )
        for enricher in self.enrichers:
            capability = enricher.capabilities()
            try:
                batch = enricher.enrich(tuple(merged.values()), request)
            except (RateLimited, NetworkTransient):
                diagnostics.append(
                    DiscoveryDiagnostic(
                        capability.provider_id,
                        "enrich",
                        "network_transient",
                        "metadata enrichment is temporarily unavailable",
                        retryable=True,
                    )
                )
                continue
            except (HttpStatusError, RuntimeError, ValueError):
                diagnostics.append(
                    DiscoveryDiagnostic(
                        capability.provider_id,
                        "enrich",
                        "provider_error",
                        "metadata enrichment failed",
                    )
                )
                continue
            diagnostics.extend(batch.diagnostics)
            covered.extend(batch.covered_slices)
            for candidate in batch.candidates:
                identity = candidate_identity(candidate)
                try:
                    merged[identity] = merge_candidates(merged.get(identity), candidate)
                except CandidateConflict:
                    diagnostics.append(
                        DiscoveryDiagnostic(
                            capability.provider_id,
                            "merge",
                            "identity_conflict",
                            "candidate identity fields conflict",
                        )
                    )
        return DiscoveryBatch(
            candidates=tuple(merged.values()),
            diagnostics=tuple(diagnostics),
            covered_slices=tuple(dict.fromkeys(covered)),
        )
