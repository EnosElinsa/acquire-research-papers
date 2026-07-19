from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

from bs4 import BeautifulSoup

from acquire_research_papers.acquisition.base import (
    AccessRequired,
    AcquiredPair,
    NotOfficial,
    PageContractChanged,
    SourceDocument,
)
from acquire_research_papers.http import HttpStatusError, SafeHttpClient
from acquire_research_papers.models import PaperMetadata, normalize_doi


ACM_HOST = "dl.acm.org"


class AcmDigitalLibraryAdapter:
    name = "acm-dl"

    def __init__(
        self,
        *,
        client: SafeHttpClient,
        production_hosts: set[str] | frozenset[str] = frozenset({ACM_HOST}),
    ) -> None:
        self.client = client
        self.production_hosts = frozenset(host.casefold() for host in production_hosts)

    @classmethod
    def for_production(cls) -> AcmDigitalLibraryAdapter:
        return cls(client=SafeHttpClient(allowed_hosts={ACM_HOST}))

    def supports(self, landing_url: str) -> bool:
        parsed = urlsplit(landing_url)
        return bool(parsed.hostname and parsed.hostname.casefold() in self.production_hosts)

    def resolve(self, landing_url: str) -> SourceDocument:
        parsed_landing = urlsplit(landing_url)
        if not self.supports(landing_url) or not parsed_landing.hostname:
            raise NotOfficial("ACM landing URL is outside dl.acm.org")
        match = re.fullmatch(r"/doi/(?:abs/)?(10\.1145/.+?)/?", unquote(parsed_landing.path))
        if not match:
            raise PageContractChanged("ACM landing path has no DOI")
        expected_doi = normalize_doi(match.group(1))
        try:
            response = self.client.get(landing_url)
        except HttpStatusError as exc:
            if exc.status_code in {401, 403}:
                raise AccessRequired("ACM page requires an authorized browser or subscription") from exc
            raise
        soup = BeautifulSoup(response.text, "html.parser")

        def values(name: str) -> list[str]:
            return [
                str(tag.get("content", "")).strip()
                for tag in soup.find_all("meta", attrs={"name": re.compile(f"^{name}$", re.I)})
                if str(tag.get("content", "")).strip()
            ]

        def one(name: str, label: str, *, required: bool = True) -> str | None:
            found = values(name)
            if len(found) > 1:
                raise PageContractChanged(f"ACM page has ambiguous {label}")
            if not found:
                if required:
                    raise PageContractChanged(f"ACM page has no {label}")
                return None
            return found[0]

        if normalize_doi(one("citation_doi", "DOI")) != expected_doi:
            raise PageContractChanged("ACM page DOI disagrees with the landing path")
        date = one("citation_publication_date", "publication date") or ""
        year_match = re.search(r"(?:19|20)\d{2}", date)
        if not year_match:
            raise PageContractChanged("ACM publication date has no year")
        authors = tuple(values("citation_author"))
        if not authors:
            raise PageContractChanged("ACM page has no authors")
        venue = one("citation_conference_title", "venue", required=False)
        if not venue:
            venue = one("citation_journal_title", "venue")
        pdf_meta = one("citation_pdf_url", "PDF URL") or ""
        pdf_path = urlsplit(pdf_meta).path
        if not pdf_path.startswith("/doi/pdf/"):
            raise PageContractChanged("ACM PDF URL is not the official DOI PDF endpoint")

        bib_links = [
            str(tag.get("href", "")).strip()
            for tag in soup.find_all(["link", "a"], href=True)
            if "/action/exportCiteProcCitation" in str(tag.get("href", ""))
        ]
        if len(bib_links) != 1:
            raise PageContractChanged("ACM page must expose one official citation export")
        bib_parts = urlsplit(bib_links[0])
        parameters = parse_qs(bib_parts.query)
        if parameters.get("format") != ["bibTex"]:
            raise PageContractChanged("ACM citation export is not raw BibTeX")
        exported_doi = normalize_doi((parameters.get("doi") or [""])[0])
        if exported_doi != expected_doi:
            raise PageContractChanged("ACM citation export DOI disagrees with the paper")

        origin = f"{parsed_landing.scheme}://{parsed_landing.netloc}"
        publication_type = one("dc.Type", "publication type", required=False)
        metadata = PaperMetadata(
            title=one("citation_title", "title") or "",
            authors=authors,
            year=int(year_match.group()),
            venue=venue or "",
            doi=expected_doi,
            publisher=one("citation_publisher", "publisher") or "",
            landing_url=landing_url,
            publication_type=publication_type or "research-article",
        )
        return SourceDocument(
            metadata=metadata,
            pdf_url=urljoin(origin, pdf_path),
            bibtex_url=urljoin(origin, bib_parts.path) + f"?{bib_parts.query}",
            allowed_hosts=frozenset({parsed_landing.hostname.casefold()}),
        )

    def acquire(self, document: SourceDocument) -> AcquiredPair:
        try:
            pdf = self.client.get(document.pdf_url).content
            bibtex = self.client.get(document.bibtex_url).text
        except HttpStatusError as exc:
            if exc.status_code in {401, 403}:
                raise AccessRequired("ACM artifact requires authorized access") from exc
            raise
        return AcquiredPair(document=document, pdf_bytes=pdf, bibtex_text=bibtex)
