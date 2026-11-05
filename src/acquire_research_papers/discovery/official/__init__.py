"""Venue-owned discovery indexes implementing the shared provider contract."""

from acquire_research_papers.discovery.official.acl import AclAnthologyDiscoveryProvider
from acquire_research_papers.discovery.official.archives import (
    ARCHIVE_INDEX_PROVIDERS,
    CvfIndexProvider,
    IclrIndexProvider,
    NeuripsIndexProvider,
    PmlrIndexProvider,
    UsenixIndexProvider,
)
from acquire_research_papers.discovery.official.ijcai import IjcaiDiscoveryProvider

__all__ = [
    "ARCHIVE_INDEX_PROVIDERS",
    "AclAnthologyDiscoveryProvider",
    "CvfIndexProvider",
    "IclrIndexProvider",
    "IjcaiDiscoveryProvider",
    "NeuripsIndexProvider",
    "PmlrIndexProvider",
    "UsenixIndexProvider",
]
