from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from acquire_research_papers.acquisition.base import (
    AcquiredPair,
    NotOfficial,
    PageContractChanged,
    SourceDocument,
)
from acquire_research_papers.http import SafeHttpClient
from acquire_research_papers.models import PaperMetadata


class DirectOfficialAdapter:
    name = "direct-official"

    def __init__(
        self,
        client: SafeHttpClient,
        *,
        production_hosts: set[str] | frozenset[str] | None = None,
    ) -> None:
        self.client = client
        self.production_hosts = frozenset(
            host.casefold().rstrip(".") for host in (production_hosts or client.allowed_hosts)
        )

    def supports(self, landing_url: str) -> bool:
        hostname = urlsplit(landing_url).hostname
        return bool(hostname and hostname.casefold().rstrip(".") in self.production_hosts)

    def _require_official_url(self, landing_url: str, value: str, label: str) -> str:
        resolved = urljoin(landing_url, value)
        hostname = urlsplit(resolved).hostname
        if not hostname or hostname.casefold().rstrip(".") not in self.production_hosts:
            raise NotOfficial(f"{label} URL is outside the publisher boundary")
        return resolved

    def resolve(self, landing_url: str) -> SourceDocument:
        if not self.supports(landing_url):
            raise NotOfficial("landing URL is outside the publisher boundary")
        response = self.client.get(landing_url)
        soup = BeautifulSoup(response.text, "html.parser")

        def metas(name: str) -> list[str]:
            return [
                str(tag.get("content", "")).strip()
                for tag in soup.find_all("meta", attrs={"name": re.compile(f"^{name}$", re.I)})
                if str(tag.get("content", "")).strip()
            ]

        def one_meta(name: str, label: str, *, required: bool = True) -> str | None:
            values = metas(name)
            if len(values) > 1:
                raise PageContractChanged(f"multiple {label} metadata values")
            if not values:
                if required:
                    raise PageContractChanged(f"missing {label} metadata")
                return None
            return values[0]

        title = one_meta("citation_title", "title")
        authors = tuple(metas("citation_author"))
        if not authors:
            raise PageContractChanged("missing author metadata")
        date = one_meta("citation_publication_date", "publication date")
        year_match = re.search(r"(?:19|20)\d{2}", date or "")
        if not year_match:
            raise PageContractChanged("publication date has no four-digit year")
        venue = one_meta("citation_journal_title", "venue", required=False)
        if not venue:
            venue = one_meta("citation_conference_title", "venue")
        publisher = one_meta("citation_publisher", "publisher")
        pdf_value = one_meta("citation_pdf_url", "PDF URL")

        bib_links = [
            str(tag.get("href", "")).strip()
            for tag in soup.find_all(["link", "a"])
            if str(tag.get("type", "")).casefold() in {"application/x-bibtex", "text/x-bibtex"}
            and str(tag.get("href", "")).strip()
        ]
        if len(bib_links) != 1:
            raise PageContractChanged("missing or ambiguous official BibTeX link")

        hostname = urlsplit(landing_url).hostname
        assert hostname is not None
        metadata = PaperMetadata(
            title=title or "",
            authors=authors,
            year=int(year_match.group()),
            venue=venue or "",
            doi=one_meta("citation_doi", "DOI", required=False),
            publisher=publisher or "",
            landing_url=landing_url,
            publication_type=one_meta("citation_article_type", "publication type", required=False),
        )
        return SourceDocument(
            metadata=metadata,
            pdf_url=self._require_official_url(landing_url, pdf_value or "", "PDF"),
            bibtex_url=self._require_official_url(landing_url, bib_links[0], "BibTeX"),
            allowed_hosts=frozenset({hostname.casefold().rstrip(".")}),
        )

    def acquire(self, document: SourceDocument) -> AcquiredPair:
        pdf_response = self.client.get(document.pdf_url)
        bibtex_response = self.client.get(document.bibtex_url)
        return AcquiredPair(
            document=document,
            pdf_bytes=pdf_response.content,
            bibtex_text=bibtex_response.text,
        )
