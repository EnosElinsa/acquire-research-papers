"""Candidate-only scholarly metadata discovery."""

from acquire_research_papers.discovery.contracts import (
    CandidateMetadata,
    CoverageSlice,
    DiscoveryBatch,
    DiscoveryProvider,
    DiscoveryRequest,
)
from acquire_research_papers.discovery.evidence import EvidencePacket

__all__ = [
    "CandidateMetadata",
    "CoverageSlice",
    "DiscoveryBatch",
    "DiscoveryProvider",
    "DiscoveryRequest",
    "EvidencePacket",
]
