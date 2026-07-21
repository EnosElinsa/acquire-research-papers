from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from acquire_research_papers.discovery.contracts import CandidateMetadata
from acquire_research_papers.http import SafeHttpClient
from acquire_research_papers.models import normalize_doi


class SemanticScholarClient:
    def __init__(
        self,
        *,
        client: SafeHttpClient,
        endpoint: str = "https://api.semanticscholar.org/recommendations/v1/papers",
        api_key: str | None = None,
    ) -> None:
        self.client = client
        self.endpoint = endpoint
        self.api_key = api_key

    @staticmethod
    def _candidate(item: dict[str, Any]) -> CandidateMetadata:
        external_ids = item.get("externalIds") or {}
        authors = tuple(
            str(author.get("name") or "").strip()
            for author in item.get("authors") or []
            if str(author.get("name") or "").strip()
        )
        abstract = str(item.get("abstract") or "").strip()
        evidence = ["title"] if item.get("title") else []
        if abstract:
            evidence.append("abstract")
        if authors:
            evidence.append("authors")
        if item.get("venue"):
            evidence.append("venue")
        publication_types = item.get("publicationTypes") or []
        return CandidateMetadata(
            key=str(item.get("paperId") or ""),
            title=str(item.get("title") or "").strip(),
            year=int(item.get("year") or 0),
            venue=str(item.get("venue") or "").strip(),
            relevance_score=0.5,
            hard_gates_passed=bool(item.get("paperId") and item.get("title") and item.get("year")),
            evidence_fields=tuple(evidence),
            doi=normalize_doi(external_ids.get("DOI")),
            official_url=None,
            authors=authors,
            abstract=abstract,
            publication_type=str(publication_types[0]) if publication_types else None,
            publication_date=str(item.get("publicationDate") or "") or None,
            citation_count=int(item.get("citationCount") or 0),
            provenance={
                "source": "semantic-scholar",
                "record_url": str(item.get("url") or ""),
            },
        )

    def recommend(
        self,
        *,
        positive_ids: list[str],
        negative_ids: list[str] | None = None,
        limit: int = 100,
    ) -> tuple[CandidateMetadata, ...]:
        fields = (
            "title,abstract,venue,year,publicationDate,publicationTypes,authors,"
            "externalIds,url,citationCount"
        )
        url = f"{self.endpoint}?{urlencode({'limit': max(1, min(limit, 500)), 'fields': fields})}"
        headers = {"x-api-key": self.api_key} if self.api_key else None
        payload = {
            "positivePaperIds": positive_ids,
            "negativePaperIds": negative_ids or [],
        }
        response = self.client.post_json(url, payload, headers=headers)
        return tuple(self._candidate(item) for item in response.json().get("recommendedPapers") or [])
