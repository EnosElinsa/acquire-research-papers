from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from acquire_research_papers.discovery.contracts import CandidateMetadata, CandidatePage
from acquire_research_papers.http import SafeHttpClient
from acquire_research_papers.models import normalize_doi


class CrossrefClient:
    def __init__(
        self,
        *,
        client: SafeHttpClient,
        endpoint: str = "https://api.crossref.org/works",
    ) -> None:
        self.client = client
        self.endpoint = endpoint

    @staticmethod
    def _candidate(item: dict[str, Any], query_url: str) -> CandidateMetadata:
        titles = item.get("title") or []
        title = str(titles[0]).strip() if titles else ""
        date_parts = (item.get("published") or {}).get("date-parts") or [[]]
        parts = date_parts[0] if date_parts else []
        year = int(parts[0]) if parts else 0
        publication_date = None
        if parts:
            padded = [int(parts[index]) if index < len(parts) else 1 for index in range(3)]
            publication_date = f"{padded[0]:04d}-{padded[1]:02d}-{padded[2]:02d}"
        venues = item.get("container-title") or []
        venue = str(venues[0]).strip() if venues else ""
        authors = tuple(
            " ".join(
                part
                for part in (str(author.get("given", "")).strip(), str(author.get("family", "")).strip())
                if part
            )
            for author in item.get("author") or []
        )
        abstract_html = str(item.get("abstract") or "")
        abstract = BeautifulSoup(abstract_html, "html.parser").get_text(" ", strip=True)
        keywords = tuple(
            value
            for subject in item.get("subject") or []
            if (value := str(subject).strip())
        )
        doi = normalize_doi(item.get("DOI"))
        primary = ((item.get("resource") or {}).get("primary") or {}).get("URL")
        official_url = str(primary or item.get("URL") or "").strip() or None
        evidence = ["title"] if title else []
        if abstract:
            evidence.append("abstract")
        if authors:
            evidence.append("authors")
        if venue:
            evidence.append("venue")
        if keywords:
            evidence.append("keywords")
        score = min(1.0, max(0.0, float(item.get("score") or 0.0) / 100.0))
        key = doi or official_url or title.casefold()
        return CandidateMetadata(
            key=key,
            title=title,
            year=year,
            venue=venue,
            relevance_score=score,
            hard_gates_passed=bool(title and year),
            evidence_fields=tuple(evidence),
            doi=doi,
            official_url=official_url,
            authors=authors,
            abstract=abstract,
            keywords=keywords,
            publication_type=str(item.get("type") or "") or None,
            publication_date=publication_date,
            citation_count=int(item.get("is-referenced-by-count") or 0),
            provenance={
                "source": "crossref",
                "query_url": query_url,
                "issn": tuple(str(value) for value in item.get("ISSN") or ()),
            },
            field_provenance={field: ("crossref",) for field in evidence},
        )

    def search(
        self,
        query: str,
        *,
        rows: int = 100,
        cursor: str = "*",
        filters: dict[str, str] | None = None,
        query_field: str = "bibliographic",
    ) -> CandidatePage:
        if query_field not in {"bibliographic", "container-title"}:
            raise ValueError("unsupported Crossref query field")
        parameters: list[tuple[str, str]] = [
            ("rows", str(max(1, min(rows, 1000)))),
            ("cursor", cursor),
            (
                "select",
                "DOI,title,author,published,container-title,publisher,type,URL,resource,abstract,subject,ISSN,score,is-referenced-by-count",
            ),
        ]
        if query:
            parameters.insert(0, (f"query.{query_field}", query))
        if filters:
            parameters.append(
                ("filter", ",".join(f"{name}:{value}" for name, value in sorted(filters.items())))
            )
        query_url = f"{self.endpoint}?{urlencode(parameters)}"
        payload = self.client.get(query_url).json()
        message = payload.get("message") or {}
        candidates = tuple(
            self._candidate(item, query_url) for item in message.get("items") or []
        )
        return CandidatePage(
            candidates=candidates,
            next_cursor=str(message.get("next-cursor")) if message.get("next-cursor") else None,
            total_results=(
                int(message["total-results"])
                if message.get("total-results") is not None
                else None
            ),
            query_url=query_url,
        )

    def corpus_searcher(self, query: str, rows: int) -> tuple[CandidateMetadata, ...]:
        return self.search(query, rows=rows).candidates
