from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlencode

from acquire_research_papers.discovery.contracts import CandidateMetadata, CandidatePage
from acquire_research_papers.http import (
    HttpStatusError,
    NetworkTransient,
    RateLimited,
    SafeHttpClient,
)
from acquire_research_papers.models import normalize_doi


class DiscoveryUnavailable(RuntimeError):
    """An optional metadata source cannot be used in the current configuration."""


_WORK_SELECT = ",".join(
    (
        "id",
        "title",
        "publication_year",
        "doi",
        "primary_location",
        "authorships",
        "abstract_inverted_index",
        "related_works",
        "relevance_score",
        "type",
        "publication_date",
        "cited_by_count",
    )
)


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
        self.graph_provider_id = "openalex"

    def _results(self, parameters: list[tuple[str, str]]) -> list[dict[str, Any]]:
        query_url = f"{self.endpoint}?{urlencode(parameters)}"
        try:
            payload = self.client.get(query_url).json()
        except RateLimited as exc:
            raise RateLimited(
                exc.status_code,
                self.endpoint,
                retry_after_seconds=exc.retry_after_seconds,
            ) from None
        except HttpStatusError as exc:
            raise DiscoveryUnavailable(
                f"OpenAlex request failed with HTTP {exc.status_code}"
            ) from None
        except NetworkTransient:
            raise NetworkTransient("OpenAlex request is temporarily unavailable") from None
        results = payload.get("results") if isinstance(payload, dict) else None
        return [item for item in results or () if isinstance(item, dict)]

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
            raise RateLimited(
                exc.status_code,
                self.endpoint,
                retry_after_seconds=exc.retry_after_seconds,
            ) from None
        except HttpStatusError as exc:
            raise DiscoveryUnavailable(
                f"OpenAlex request failed with HTTP {exc.status_code}"
            ) from None
        except NetworkTransient:
            raise NetworkTransient("OpenAlex request is temporarily unavailable") from None
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

    def lookup_dois(self, dois: list[str]) -> tuple[CandidateMetadata, ...]:
        normalized = list(
            dict.fromkeys(
                value
                for doi in dois
                if (value := normalize_doi(doi)) is not None
            )
        )
        if not normalized:
            return ()
        if len(normalized) > 100:
            raise ValueError("OpenAlex DOI lookup accepts at most 100 unique values.")
        if not self.api_key:
            raise DiscoveryUnavailable("OpenAlex API key is not configured")
        parameters = {
            "filter": "doi:"
            + "|".join(f"https://doi.org/{doi}" for doi in normalized),
            "per-page": "100",
            "select": _WORK_SELECT,
            "api_key": self.api_key,
        }
        query_url = f"{self.endpoint}?{urlencode(parameters)}"
        try:
            payload = self.client.get(query_url).json()
        except RateLimited as exc:
            raise RateLimited(
                exc.status_code,
                self.endpoint,
                retry_after_seconds=exc.retry_after_seconds,
            ) from None
        except HttpStatusError as exc:
            raise DiscoveryUnavailable(
                f"OpenAlex request failed with HTTP {exc.status_code}"
            ) from None
        except NetworkTransient:
            raise NetworkTransient("OpenAlex request is temporarily unavailable") from None
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            return ()
        by_doi: dict[str, CandidateMetadata] = {}
        for item in results:
            if not isinstance(item, dict):
                continue
            candidate = self._candidate(item, self.endpoint)
            if candidate.doi:
                by_doi.setdefault(normalize_doi(candidate.doi) or "", candidate)
        return tuple(by_doi[doi] for doi in normalized if doi in by_doi)

    def _graph_seed(self, seed: str) -> tuple[str, tuple[str, ...]] | None:
        if not self.api_key:
            raise DiscoveryUnavailable("OpenAlex API key is not configured")
        raw = seed.strip().rstrip("/")
        openalex_id = raw.rsplit("/", 1)[-1] if raw.upper().startswith("W") or "openalex.org/" in raw else ""
        if openalex_id.upper().startswith("W"):
            filter_value = f"openalex:{openalex_id}"
        else:
            doi = normalize_doi(raw)
            if not doi or not re.match(r"^10\.\d{4,9}/\S+$", doi):
                return None
            filter_value = f"doi:https://doi.org/{doi}"
        rows = self._results(
            [
                ("filter", filter_value),
                ("per-page", "1"),
                ("select", "id,referenced_works"),
                ("api_key", self.api_key),
            ]
        )
        if not rows:
            return None
        seed_id = str(rows[0].get("id") or "").rstrip("/").rsplit("/", 1)[-1]
        references = tuple(
            str(value).rstrip("/").rsplit("/", 1)[-1]
            for value in rows[0].get("referenced_works") or ()
            if str(value).strip()
        )
        return seed_id, references

    def expand(
        self,
        seed: str,
        direction: str,
        limit: int,
    ) -> tuple[CandidateMetadata, ...]:
        """Expand one bounded OpenAlex references, citations, or related hop."""
        resolved = self._graph_seed(seed)
        if resolved is None:
            return ()
        seed_id, references = resolved
        if direction == "references":
            identifiers = references[: max(1, min(limit, 100))]
            if not identifiers:
                return ()
            graph_filter = "openalex:" + "|".join(identifiers)
        elif direction == "citations":
            graph_filter = f"cites:{seed_id}"
        elif direction == "related":
            graph_filter = f"related_to:{seed_id}"
        else:
            raise ValueError(f"unsupported OpenAlex graph direction: {direction}")
        per_page = max(1, min(limit, 100))
        rows = self._results(
            [
                ("filter", graph_filter),
                ("per-page", str(per_page)),
                ("select", _WORK_SELECT),
                ("api_key", self.api_key or ""),
            ]
        )
        return tuple(self._candidate(item, self.endpoint) for item in rows)
