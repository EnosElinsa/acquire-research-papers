"""Springer Link journal articles and book chapters (link.springer.com).

The landing page names the article's DOI, its PDF, and Springer's citation export service; the
adapter accepts the page only when these agree with the landing path. Springer states on the
page whether this network may read the PDF (``hasAccess``): open-access papers always, and
subscription papers on an entitled network. Without access the paper is a manual download.
The BibTeX file is Springer's own citation export for the DOI; it is never generated.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

from acquire_research_papers.acquisition.adapters._page import LandingPage
from acquire_research_papers.acquisition.base import (
    AccessRequired,
    AcquiredPair,
    NotOfficial,
    PageContractChanged,
    SourceDocument,
)
from acquire_research_papers.bibliography import BibMissing, decode_bibtex_bytes
from acquire_research_papers.http import HostBoundaryError, SafeHttpClient
from acquire_research_papers.models import PaperMetadata, normalize_doi
from acquire_research_papers.resolver import UnsupportedPublisher

SPRINGER_HOST = "link.springer.com"
CITATION_HOST = "citation-needed.springer.com"
# Springer answers a first visit with a cookie handshake on this host before the article page.
COOKIE_HOST = "idp.springer.com"

_LANDING_PATH = re.compile(r"/(article|chapter)/(10\.1007/[^?#]+)")
# DOI targets use the short /10.1007/... form, which redirects to the article or chapter page.
_SHORT_PATH = re.compile(r"/(10\.1007/[^?#]+)")
_HAS_ACCESS = re.compile(r'"hasAccess"\s*:\s*"([YN])"')
_NO_ACCESS = (
    "Springer does not grant this network access to the PDF; download it from the article page "
    "with your institution's access and import it with manual-fetch"
)


def _requested_doi(path: str) -> str | None:
    match = _LANDING_PATH.fullmatch(path) or _SHORT_PATH.fullmatch(path)
    return normalize_doi(match.groups()[-1]) if match else None


class SpringerLinkAdapter:
    name = "springer-link"
    production_hosts = frozenset({SPRINGER_HOST})

    def __init__(self, client: SafeHttpClient) -> None:
        self.client = client

    @classmethod
    def for_production(cls, **client_options) -> SpringerLinkAdapter:
        return cls(SafeHttpClient(allowed_hosts={SPRINGER_HOST, COOKIE_HOST, CITATION_HOST},
                                  **client_options))

    def supports(self, landing_url: str) -> bool:
        hostname = urlsplit(landing_url).hostname
        return bool(hostname and hostname.casefold().rstrip(".") == SPRINGER_HOST)

    def resolve(self, landing_url: str) -> SourceDocument:
        if not self.supports(landing_url):
            raise NotOfficial("Springer landing URL is outside link.springer.com")
        requested = _requested_doi(unquote(urlsplit(landing_url).path))
        if requested is None:
            raise UnsupportedPublisher(
                "only Springer Link article and chapter pages have an adapter")
        response = self.client.get(landing_url)
        final_url = str(response.url)
        final = urlsplit(final_url)
        match = _LANDING_PATH.fullmatch(unquote(final.path))
        if (final.hostname or "").casefold() != SPRINGER_HOST or not match:
            raise UnsupportedPublisher(
                "only Springer Link article and chapter pages have an adapter")
        kind, path_doi = match.group(1), normalize_doi(match.group(2))
        if path_doi != requested:
            raise PageContractChanged("Springer redirected to a different DOI")
        page = LandingPage(f"https://{SPRINGER_HOST}{final.path}", response.text, "Springer")
        doi = normalize_doi(page.one("citation_doi", "DOI"))
        if doi != path_doi:
            raise PageContractChanged("Springer page DOI disagrees with the landing path")
        pdf_path = page.meta_path("citation_pdf_url", "PDF metadata")
        if unquote(pdf_path).casefold() != f"/content/pdf/{doi}.pdf":
            raise PageContractChanged("Springer PDF URL does not match the DOI")
        if not self._exports_citation(page, doi):
            raise PageContractChanged("Springer page links no citation export for the DOI")
        # Without the marker (a changed layout) the PDF response itself decides below.
        has_access = _HAS_ACCESS.findall(response.text)
        if has_access and set(has_access) != {"Y"}:
            raise AccessRequired(_NO_ACCESS)
        landing = page.landing_url
        venue_names = (("citation_journal_title",) if kind == "article"
                       else ("citation_inbook_title", "citation_book_title"))
        return SourceDocument(
            metadata=PaperMetadata(
                title=page.one("citation_title", "title") or "",
                authors=page.authors(family_first=True),
                year=page.year("citation_publication_date", "publication date"),
                venue=page.first(venue_names, "venue"),
                doi=doi,
                publisher="Springer",
                landing_url=landing,
                publication_type="research-article" if kind == "article" else "chapter",
            ),
            pdf_url=f"https://{SPRINGER_HOST}{pdf_path}",
            bibtex_url=(f"https://{CITATION_HOST}/v2/references/{doi}"
                        "?format=bibtex&flavour=citation"),
            allowed_hosts=frozenset({SPRINGER_HOST, CITATION_HOST}),
        )

    @staticmethod
    def _exports_citation(page: LandingPage, doi: str) -> bool:
        """The page links Springer's citation export for exactly this DOI (any format)."""
        for anchor in page.soup.find_all("a", href=True):
            target = urlsplit(urljoin(page.landing_url, str(anchor["href"])))
            if ((target.hostname or "").casefold() == CITATION_HOST
                    and normalize_doi(unquote(target.path).removeprefix("/v2/references/")) == doi
                    and parse_qs(target.query).get("flavour") == ["citation"]):
                return True
        return False

    def acquire(self, document: SourceDocument) -> AcquiredPair:
        try:
            pdf = self.client.get(document.pdf_url)
        except HostBoundaryError as exc:
            # A paywall sends the PDF request to a sign-in host outside the adapter boundary.
            raise AccessRequired(_NO_ACCESS) from exc
        if not pdf.content.startswith(b"%PDF"):
            raise AccessRequired(_NO_ACCESS)
        raw = self.client.get(document.bibtex_url).content
        text = decode_bibtex_bytes(raw)[0]
        if not text.lstrip().startswith("@"):
            raise BibMissing("Springer citation export returned no BibTeX entry")
        return AcquiredPair(
            document=document,
            pdf_bytes=pdf.content,
            bibtex_text=text,
            bibtex_bytes=raw,
            bibtex_source="publisher_download",
        )
