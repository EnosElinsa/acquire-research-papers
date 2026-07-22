from __future__ import annotations

import html as html_lib
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
from acquire_research_papers.models import PaperMetadata, normalize_doi


_LANDING_PATH = re.compile(r"^/proceedings/((?:19|20)\d{2})/(\d+)/?$")
_TRACK = re.compile(r"^([A-Za-z][A-Za-z &/-]*Track)\.\s*Pages\b", re.IGNORECASE)


class IjcaiProceedingsAdapter:
    name = "ijcai-proceedings"

    def __init__(
        self,
        client: SafeHttpClient,
        *,
        production_hosts: set[str] | frozenset[str] = frozenset({"www.ijcai.org"}),
    ) -> None:
        self.client = client
        self.production_hosts = frozenset(host.casefold() for host in production_hosts)

    def supports(self, landing_url: str) -> bool:
        parsed = urlsplit(landing_url)
        return bool(parsed.hostname and parsed.hostname.casefold() in self.production_hosts)

    @staticmethod
    def _publication_type(track: str) -> str:
        normalized = track.casefold()
        if "main track" in normalized:
            return "main"
        if "demo" in normalized:
            return "demo"
        if "special track" in normalized:
            return "special"
        return re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")

    def resolve(self, landing_url: str) -> SourceDocument:
        if not self.supports(landing_url):
            raise NotOfficial("IJCAI landing URL is outside www.ijcai.org")
        return self.parse(landing_url, self.client.get(landing_url).text)

    def parse(self, landing_url: str, html: str) -> SourceDocument:
        parsed_landing = urlsplit(landing_url)
        if not self.supports(landing_url) or not parsed_landing.hostname:
            raise NotOfficial("IJCAI landing URL is outside www.ijcai.org")
        match = _LANDING_PATH.fullmatch(parsed_landing.path)
        if not match:
            raise PageContractChanged("IJCAI landing path is not a proceedings paper")
        year, number = match.groups()
        soup = BeautifulSoup(html, "html.parser")

        def values(name: str) -> list[str]:
            return [
                html_lib.unescape(str(tag.get("content", "")).strip())
                for tag in soup.find_all("meta", attrs={"name": re.compile(f"^{name}$", re.I)})
                if str(tag.get("content", "")).strip()
            ]

        def one(name: str, label: str) -> str:
            found = values(name)
            if len(found) != 1:
                raise PageContractChanged(f"IJCAI page has missing or ambiguous {label}")
            return found[0]

        pdf_links: list[str] = []
        bibtex_links: list[str] = []
        for anchor in soup.find_all("a", href=True):
            label = anchor.get_text(" ", strip=True).casefold()
            if label == "pdf":
                pdf_links.append(str(anchor["href"]))
            elif label == "bibtex":
                bibtex_links.append(str(anchor["href"]))
        if len(pdf_links) != 1 or len(bibtex_links) != 1:
            raise PageContractChanged("IJCAI page must expose one PDF and one BibTeX link")

        pdf_path = urlsplit(pdf_links[0]).path
        pdf_match = re.fullmatch(rf"/proceedings/{year}/(\d+)\.pdf", pdf_path)
        if not pdf_match or int(pdf_match.group(1)) != int(number):
            raise PageContractChanged("IJCAI PDF URL does not match the proceedings ID")
        if urlsplit(one("citation_pdf_url", "PDF metadata")).path != pdf_path:
            raise PageContractChanged("IJCAI visible and metadata PDF URLs disagree")
        expected_bib_path = f"/proceedings/{year}/bibtex/{number}"
        if urlsplit(bibtex_links[0]).path.rstrip("/") != expected_bib_path:
            raise PageContractChanged("IJCAI BibTeX URL does not match the proceedings ID")

        expected_doi = f"10.24963/ijcai.{year}/{int(number)}"
        if normalize_doi(one("citation_doi", "DOI")) != expected_doi:
            raise PageContractChanged("IJCAI DOI does not match the proceedings ID")
        track = next(
            (
                track_match.group(1)
                for text in soup.stripped_strings
                if (track_match := _TRACK.search(text))
            ),
            None,
        )
        if not track:
            raise PageContractChanged("IJCAI page has no publication track")
        date = one("citation_publication_date", "publication date")
        if year not in date:
            raise PageContractChanged("IJCAI publication year disagrees with landing path")
        authors = tuple(values("citation_author"))
        if not authors:
            raise PageContractChanged("IJCAI page has no authors")

        origin = f"{parsed_landing.scheme}://{parsed_landing.netloc}"
        document = SourceDocument(
            metadata=PaperMetadata(
                title=one("citation_title", "title"),
                authors=authors,
                year=int(year),
                venue=one("citation_conference_title", "conference title"),
                doi=expected_doi,
                publisher="International Joint Conferences on Artificial Intelligence Organization",
                landing_url=landing_url,
                publication_type=self._publication_type(track),
            ),
            pdf_url=urljoin(origin, pdf_path),
            bibtex_url=urljoin(origin, expected_bib_path),
            allowed_hosts=frozenset({parsed_landing.hostname.casefold()}),
        )
        return document

    def matches_track(self, document: SourceDocument, *, allowed: set[str]) -> bool:
        publication_type = document.metadata.publication_type or ""
        return publication_type.casefold() in {value.casefold() for value in allowed}

    def acquire(self, document: SourceDocument) -> AcquiredPair:
        return AcquiredPair(
            document=document,
            pdf_bytes=self.client.get(document.pdf_url).content,
            bibtex_text=self.client.get(document.bibtex_url).text,
        )
