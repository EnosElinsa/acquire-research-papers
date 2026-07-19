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
from acquire_research_papers.models import PaperMetadata, normalize_doi


_ANTHOLOGY_ID = re.compile(r"^(?:19|20)\d{2}\.[a-z0-9-]+\.\d+$", re.IGNORECASE)


class AclAnthologyAdapter:
    name = "acl-anthology"

    def __init__(
        self,
        client: SafeHttpClient,
        *,
        production_hosts: set[str] | frozenset[str] = frozenset({"aclanthology.org"}),
    ) -> None:
        self.client = client
        self.production_hosts = frozenset(host.casefold() for host in production_hosts)

    def supports(self, landing_url: str) -> bool:
        parsed = urlsplit(landing_url)
        return bool(parsed.hostname and parsed.hostname.casefold() in self.production_hosts)

    def resolve(self, landing_url: str) -> SourceDocument:
        parsed_landing = urlsplit(landing_url)
        if not self.supports(landing_url) or not parsed_landing.hostname:
            raise NotOfficial("ACL landing URL is outside aclanthology.org")
        anthology_id = parsed_landing.path.rstrip("/").rsplit("/", 1)[-1]
        if not _ANTHOLOGY_ID.fullmatch(anthology_id):
            raise PageContractChanged("ACL landing path has no valid Anthology ID")

        soup = BeautifulSoup(self.client.get(landing_url).text, "html.parser")

        def values(name: str) -> list[str]:
            return [
                str(tag.get("content", "")).strip()
                for tag in soup.find_all("meta", attrs={"name": re.compile(f"^{name}$", re.I)})
                if str(tag.get("content", "")).strip()
            ]

        def one(name: str, label: str) -> str:
            found = values(name)
            if len(found) != 1:
                raise PageContractChanged(f"ACL page has missing or ambiguous {label}")
            return found[0]

        expected_pdf_path = f"/{anthology_id}.pdf"
        pdf_meta = one("citation_pdf_url", "PDF metadata")
        if urlsplit(pdf_meta).path != expected_pdf_path:
            raise PageContractChanged("ACL PDF URL does not match the Anthology ID")
        expected_doi = f"10.18653/v1/{anthology_id}".casefold()
        if normalize_doi(one("citation_doi", "DOI")) != expected_doi:
            raise PageContractChanged("ACL DOI does not match the Anthology ID")
        date = one("citation_publication_date", "publication date")
        year_match = re.search(r"(?:19|20)\d{2}", date)
        if not year_match:
            raise PageContractChanged("ACL publication date has no year")
        authors = tuple(values("citation_author"))
        if not authors:
            raise PageContractChanged("ACL page has no authors")
        venue = one("citation_conference_title", "conference title")

        publication_type = "research-article"
        if "-long." in anthology_id:
            publication_type = "full"
        elif "-short." in anthology_id:
            publication_type = "short"
        elif "demo" in anthology_id:
            publication_type = "demo"

        origin = f"{parsed_landing.scheme}://{parsed_landing.netloc}"
        metadata = PaperMetadata(
            title=one("citation_title", "title"),
            authors=authors,
            year=int(year_match.group()),
            venue=venue,
            doi=expected_doi,
            publisher="Association for Computational Linguistics",
            landing_url=landing_url,
            publication_type=publication_type,
        )
        return SourceDocument(
            metadata=metadata,
            pdf_url=urljoin(origin, expected_pdf_path),
            bibtex_url=urljoin(origin, f"/{anthology_id}.bib"),
            allowed_hosts=frozenset({parsed_landing.hostname.casefold()}),
        )

    def acquire(self, document: SourceDocument) -> AcquiredPair:
        return AcquiredPair(
            document=document,
            pdf_bytes=self.client.get(document.pdf_url).content,
            bibtex_text=self.client.get(document.bibtex_url).text,
        )
