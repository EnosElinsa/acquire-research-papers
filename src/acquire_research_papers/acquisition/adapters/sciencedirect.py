from __future__ import annotations

import re
from urllib.parse import urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup

from acquire_research_papers.acquisition.base import (
    AccessRequired,
    AcquiredPair,
    NotOfficial,
    PageContractChanged,
    SourceDocument,
)
from acquire_research_papers.http import HttpStatusError, SafeHttpClient
from acquire_research_papers.models import PaperMetadata


SCIENCEDIRECT_HOST = "www.sciencedirect.com"
_PII_PATH = re.compile(r"^/science/article/(?:abs/)?pii/([A-Z0-9]+)/?$")


class ScienceDirectAdapter:
    name = "sciencedirect"

    def __init__(
        self,
        *,
        client: SafeHttpClient,
        production_hosts: set[str] | frozenset[str] = frozenset({SCIENCEDIRECT_HOST}),
    ) -> None:
        self.client = client
        self.production_hosts = frozenset(host.casefold() for host in production_hosts)

    @classmethod
    def for_production(cls) -> ScienceDirectAdapter:
        return cls(client=SafeHttpClient(allowed_hosts={SCIENCEDIRECT_HOST}))

    def supports(self, landing_url: str) -> bool:
        parsed = urlsplit(landing_url)
        return bool(parsed.hostname and parsed.hostname.casefold() in self.production_hosts)

    def resolve(self, landing_url: str) -> SourceDocument:
        parsed_landing = urlsplit(landing_url)
        if not self.supports(landing_url) or not parsed_landing.hostname:
            raise NotOfficial("ScienceDirect landing URL is outside the official host")
        match = _PII_PATH.fullmatch(parsed_landing.path)
        if not match:
            raise PageContractChanged("ScienceDirect landing path has no PII")
        pii = match.group(1)
        try:
            response = self.client.get(landing_url)
        except HttpStatusError as exc:
            if exc.status_code in {401, 403}:
                raise AccessRequired(
                    "ScienceDirect requires the current campus/IP entitlement or open access"
                ) from exc
            raise
        soup = BeautifulSoup(response.text, "html.parser")

        def values(name: str) -> list[str]:
            return [
                str(tag.get("content", "")).strip()
                for tag in soup.find_all("meta", attrs={"name": re.compile(f"^{name}$", re.I)})
                if str(tag.get("content", "")).strip()
            ]

        def one(name: str, label: str) -> str:
            found = values(name)
            if len(found) != 1:
                raise PageContractChanged(f"ScienceDirect page has missing or ambiguous {label}")
            return found[0]

        authors = tuple(values("citation_author"))
        if not authors:
            raise PageContractChanged("ScienceDirect page has no authors")
        date = one("citation_publication_date", "publication date")
        year_match = re.search(r"(?:19|20)\d{2}", date)
        if not year_match:
            raise PageContractChanged("ScienceDirect publication date has no year")

        pdf_candidates = values("citation_pdf_url")
        pdf_candidates.extend(
            str(anchor.get("href", "")).strip()
            for anchor in soup.find_all("a", href=True)
            if "/pdfft" in str(anchor.get("href", ""))
        )
        unique_pdf = []
        for value in pdf_candidates:
            if value and value not in unique_pdf:
                unique_pdf.append(value)
        if not unique_pdf:
            raise AccessRequired(
                "ScienceDirect did not expose an authorized PDF in the current campus/IP context"
            )
        if len(unique_pdf) != 1:
            raise PageContractChanged("ScienceDirect page exposes ambiguous PDF links")
        pdf_parts = urlsplit(unique_pdf[0])
        expected_prefix = f"/science/article/pii/{pii}/pdfft"
        if pdf_parts.path != expected_prefix:
            raise PageContractChanged("ScienceDirect PDF URL does not match the article PII")

        origin = f"{parsed_landing.scheme}://{parsed_landing.netloc}"
        pdf_url = urljoin(origin, pdf_parts.path)
        if pdf_parts.query:
            pdf_url += f"?{pdf_parts.query}"
        bibtex_url = urljoin(origin, "/sdfe/arp/cite") + "?" + urlencode(
            [("pii", pii), ("format", "text/x-bibtex"), ("withabstract", "true")]
        )
        metadata = PaperMetadata(
            title=one("citation_title", "title"),
            authors=authors,
            year=int(year_match.group()),
            venue=one("citation_journal_title", "journal title"),
            doi=one("citation_doi", "DOI"),
            publisher=one("citation_publisher", "publisher"),
            landing_url=landing_url,
            publication_type="research-article",
        )
        return SourceDocument(
            metadata=metadata,
            pdf_url=pdf_url,
            bibtex_url=bibtex_url,
            allowed_hosts=frozenset({parsed_landing.hostname.casefold()}),
        )

    def acquire(self, document: SourceDocument) -> AcquiredPair:
        try:
            pdf = self.client.get(document.pdf_url).content
            bibtex = self.client.get(document.bibtex_url).text
        except HttpStatusError as exc:
            if exc.status_code in {401, 403}:
                raise AccessRequired(
                    "ScienceDirect artifact is unavailable in the current campus/IP context"
                ) from exc
            raise
        return AcquiredPair(document=document, pdf_bytes=pdf, bibtex_text=bibtex)
