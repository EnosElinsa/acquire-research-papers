from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import quote, urlencode

from acquire_research_papers.discovery.contracts import CandidateMetadata
from acquire_research_papers.http import RateLimited, SafeHttpClient
from acquire_research_papers.models import normalize_doi


class SemanticScholarRequestPacer:
    """Serialize requests against Semantic Scholar's cross-endpoint rate limit."""

    def __init__(
        self,
        *,
        minimum_interval_seconds: float = 1.25,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.minimum_interval_seconds = max(0.0, minimum_interval_seconds)
        self.clock = clock
        self.sleeper = sleeper
        self._next_request_at = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = self.clock()
            delay = self._next_request_at - now
            if delay > 0:
                self.sleeper(delay)
                now = self.clock()
            self._next_request_at = max(now, self._next_request_at) + (
                self.minimum_interval_seconds
            )


class SemanticScholarClient:
    def __init__(
        self,
        *,
        client: SafeHttpClient,
        endpoint: str = "https://api.semanticscholar.org/recommendations/v1/papers",
        search_endpoint: str = "https://api.semanticscholar.org/graph/v1/paper/search",
        batch_endpoint: str = "https://api.semanticscholar.org/graph/v1/paper/batch",
        graph_endpoint: str = "https://api.semanticscholar.org/graph/v1/paper",
        api_key: str | None = None,
        request_pacer: SemanticScholarRequestPacer | None = None,
        rate_limit_retries: int = 4,
        rate_limit_backoff_seconds: float = 2.0,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client
        self.endpoint = endpoint
        self.search_endpoint = search_endpoint
        self.batch_endpoint = batch_endpoint
        self.graph_endpoint = graph_endpoint.rstrip("/")
        self.graph_provider_id = "semantic-scholar"
        self.api_key = api_key
        self.request_pacer = request_pacer or SemanticScholarRequestPacer(
            sleeper=sleeper
        )
        self.rate_limit_retries = max(0, rate_limit_retries)
        self.rate_limit_backoff_seconds = max(0.0, rate_limit_backoff_seconds)
        self.sleeper = sleeper

    def _request(
        self,
        operation: Callable[[], Any],
        *,
        endpoint: str,
    ) -> Any:
        for attempt in range(self.rate_limit_retries + 1):
            self.request_pacer.wait()
            try:
                return operation()
            except RateLimited as exc:
                if attempt == self.rate_limit_retries:
                    raise RateLimited(
                        429,
                        endpoint,
                        retry_after_seconds=exc.retry_after_seconds,
                    ) from None
                delay = exc.retry_after_seconds
                if delay is None:
                    delay = self.rate_limit_backoff_seconds * (2**attempt)
                self.sleeper(delay)
        raise AssertionError("Semantic Scholar retry loop escaped its bound")

    @staticmethod
    def _candidate(item: dict[str, Any], query_url: str = "") -> CandidateMetadata:
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
                **({"query_url": query_url} if query_url else {}),
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
        response = self._request(
            lambda: self.client.post_json(url, payload, headers=headers),
            endpoint=self.endpoint,
        )
        return tuple(self._candidate(item) for item in response.json().get("recommendedPapers") or [])

    def corpus_searcher(self, query: str, rows: int) -> tuple[CandidateMetadata, ...]:
        fields = (
            "paperId,title,abstract,venue,year,publicationDate,publicationTypes,"
            "authors,externalIds,url,citationCount"
        )
        parameters = {
            "query": query,
            "limit": max(1, min(rows, 100)),
            "fields": fields,
        }
        query_url = f"{self.search_endpoint}?{urlencode(parameters)}"
        headers = {"x-api-key": self.api_key} if self.api_key else None
        payload = self._request(
            lambda: self.client.get(query_url, headers=headers),
            endpoint=self.search_endpoint,
        ).json()
        return tuple(
            self._candidate(item, query_url) for item in payload.get("data") or ()
        )

    def lookup_dois(self, dois: list[str]) -> tuple[CandidateMetadata, ...]:
        if not dois:
            return ()
        fields = (
            "paperId,title,abstract,venue,year,publicationDate,publicationTypes,"
            "authors,externalIds,url,citationCount"
        )
        url = f"{self.batch_endpoint}?{urlencode({'fields': fields})}"
        headers = {"x-api-key": self.api_key} if self.api_key else None
        payload = self._request(
            lambda: self.client.post_json(
                url,
                {"ids": [f"DOI:{normalize_doi(doi)}" for doi in dois]},
                headers=headers,
            ),
            endpoint=self.batch_endpoint,
        ).json()
        if not isinstance(payload, list):
            return ()
        return tuple(
            self._candidate(item)
            for item in payload
            if isinstance(item, dict) and item.get("paperId")
        )

    @staticmethod
    def _paper_identifier(seed: str) -> str:
        raw = seed.strip()
        if not raw:
            return ""
        if re.match(r"(?i)^(corpusid|arxiv|mag|acl|pmid|pmcid|url):", raw):
            return raw
        normalized = normalize_doi(raw)
        if normalized and re.match(r"^10\.\d{4,9}/\S+$", normalized):
            return f"DOI:{normalized}"
        return raw

    def expand(
        self,
        seed: str,
        direction: str,
        limit: int,
    ) -> tuple[CandidateMetadata, ...]:
        """Expand one bounded citation-graph hop from an exact paper seed."""
        identifier = self._paper_identifier(seed)
        if not identifier:
            return ()
        if direction == "related":
            return self.recommend(
                positive_ids=[identifier],
                limit=max(1, min(limit, 500)),
            )
        relation_key = {
            "references": "citedPaper",
            "citations": "citingPaper",
        }.get(direction)
        if relation_key is None:
            raise ValueError(f"unsupported Semantic Scholar graph direction: {direction}")
        fields = (
            "paperId,title,abstract,venue,year,publicationDate,publicationTypes,"
            "authors,externalIds,url,citationCount"
        )
        relation_endpoint = (
            f"{self.graph_endpoint}/{quote(identifier, safe=':')}/{direction}"
        )
        query_url = f"{relation_endpoint}?{urlencode({'limit': max(1, min(limit, 1000)), 'fields': fields})}"
        headers = {"x-api-key": self.api_key} if self.api_key else None
        payload = self._request(
            lambda: self.client.get(query_url, headers=headers),
            endpoint=relation_endpoint,
        ).json()
        return tuple(
            self._candidate(paper)
            for row in payload.get("data") or ()
            if isinstance(row, dict)
            and isinstance((paper := row.get(relation_key)), dict)
            and paper.get("paperId")
        )
