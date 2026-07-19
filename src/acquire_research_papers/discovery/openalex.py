from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from acquire_research_papers.discovery.corpus import CandidateMetadata, CandidatePage
from acquire_research_papers.http import HttpStatusError, RateLimited, SafeHttpClient
from acquire_research_papers.models import normalize_doi


class DiscoveryUnavailable(RuntimeError):
    """An optional metadata source cannot be used in the current configuration."""


def _abstract(index: dict[str, list[int]] | None) -> str:
    if not index:
        return ""
    maximum = max((position for positions in index.values() for position in positions), default=-1)
    words = [""] * (maximum + 1)
    for word, positions in index.items():
        for position in positions:
            if 0 <= position < len(words):
                words[position] = word
    return " ".join(word for word in words if word)


class OpenAlexClient:
    def __init__(
        self,
        *,
        client: SafeHttpClient,
        api_key: str | None,
        endpoint: str = "https://api.openalex.org/works",
    ) -> None:
        self.client = client
        self.api_key = api_key
        self.endpoint = endpoint

    @staticmethod
    def _candidate(item: dict[str, Any], query_url: str) -> CandidateMetadata:
        openalex_id = str(item.get("id") or "")
        key = openalex_id.rstrip("/").rsplit("/", 1)[-1]
        location = item.get("primary_location") or {}
        source = location.get("source") or {}
        authors = tuple(
            str((authorship.get("author") or {}).get("display_name") or "").strip()
            for authorship in item.get("authorships") or []
            if str((authorship.get("author") or {}).get("display_name") or "").strip()
        )
        abstract = _abstract(item.get("abstract_inverted_index"))
        related = tuple(
            str(value).rstrip("/").rsplit("/", 1)[-1]
            for value in item.get("related_works") or []
        )
        evidence = ["title"] if item.get("title") else []
        if abstract:
            evidence.append("abstract")
        if authors:
            evidence.append("authors")
        if source.get("display_name"):
            evidence.append("venue")
        raw_score = float(item.get("relevance_score") or 0.0)
        score = max(0.0, min(1.0, raw_score if raw_score <= 1 else raw_score / 100.0))
        return CandidateMetadata(
            key=key,
            title=str(item.get("title") or "").strip(),
            year=int(item.get("publication_year") or 0),
            venue=str(source.get("display_name") or "").strip(),
            relevance_score=score,
            hard_gates_passed=bool(key and item.get("title") and item.get("publication_year")),
            evidence_fields=tuple(evidence),
            doi=normalize_doi(item.get("doi")),
            official_url=str(location.get("landing_page_url") or "").strip() or None,
            authors=authors,
            abstract=abstract,
            publication_type=str(item.get("type") or "") or None,
            publication_date=str(item.get("publication_date") or "") or None,
            citation_count=int(item.get("cited_by_count") or 0),
            related_ids=related,
            provenance={"source": "openalex", "query_url": query_url},
        )

    def search(
        self,
        query: str,
        *,
        per_page: int = 100,
        cursor: str = "*",
        filters: str | None = None,
    ) -> CandidatePage:
        if not self.api_key:
            raise DiscoveryUnavailable("OpenAlex API key is not configured")
        parameters = [
            ("search", query),
            ("per-page", str(max(1, min(per_page, 100)))),
            ("cursor", cursor),
            ("api_key", self.api_key),
        ]
        if filters:
            parameters.append(("filter", filters))
        query_url = f"{self.endpoint}?{urlencode(parameters)}"
        try:
            payload = self.client.get(query_url).json()
        except RateLimited as exc:
            raise RateLimited(exc.status_code, self.endpoint) from exc
        except HttpStatusError as exc:
            raise DiscoveryUnavailable(f"OpenAlex request failed with HTTP {exc.status_code}") from exc
        candidates = tuple(
            self._candidate(item, self.endpoint) for item in payload.get("results") or []
        )
        meta = payload.get("meta") or {}
        return CandidatePage(
            candidates=candidates,
            next_cursor=str(meta.get("next_cursor")) if meta.get("next_cursor") else None,
        )

    def corpus_searcher(self, query: str, rows: int) -> tuple[CandidateMetadata, ...]:
        return self.search(query, per_page=rows).candidates
