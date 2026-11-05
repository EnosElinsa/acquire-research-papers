"""Official open-access conference archives: AAAI (OJS), NeurIPS, ICLR, PMLR, CVF, and USENIX.

Each adapter derives the expected PDF and BibTeX locations from the landing path and accepts
the page only when its citation metadata agrees. PMLR and CVF publish no BibTeX file, and
USENIX serves its file only behind a browser bot check; for these the official BibTeX is the
entry printed on the landing page, recorded as ``publisher_page_embedded`` provenance.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from acquire_research_papers.acquisition.adapters._page import LandingPage, same_origin
from acquire_research_papers.acquisition.base import (
    AcquiredPair,
    NotOfficial,
    PageContractChanged,
    SourceDocument,
)
from acquire_research_papers.bibliography import decode_bibtex_bytes
from acquire_research_papers.http import SafeHttpClient
from acquire_research_papers.models import PaperMetadata, normalize_doi

EMBEDDED_BIBTEX_SOURCE = "publisher_page_embedded"
_BIBTEX_KEY = re.compile(r"\s*@\w+\s*\{\s*([^,\s]+)\s*,")


@dataclass(frozen=True)
class PageContract:
    metadata: PaperMetadata
    pdf_path: str
    bibtex_path: str | None = None
    embedded_bibtex: str | None = None


class _OpenAccessAdapter:
    name = ""
    label = ""
    default_hosts: frozenset[str] = frozenset()

    def __init__(
        self,
        client: SafeHttpClient,
        *,
        production_hosts: set[str] | frozenset[str] | None = None,
    ) -> None:
        self.client = client
        self.production_hosts = frozenset(
            host.casefold().rstrip(".") for host in (production_hosts or self.default_hosts)
        )
        self._embedded: dict[str, str] = {}

    @classmethod
    def for_production(cls, **client_options) -> _OpenAccessAdapter:
        return cls(SafeHttpClient(allowed_hosts=cls.default_hosts, **client_options))

    def supports(self, landing_url: str) -> bool:
        hostname = urlsplit(landing_url).hostname
        return bool(hostname and hostname.casefold().rstrip(".") in self.production_hosts)

    def parse(self, path: str, page: LandingPage) -> PageContract:
        raise NotImplementedError

    def resolve(self, landing_url: str) -> SourceDocument:
        if not self.supports(landing_url):
            raise NotOfficial(f"{self.label} landing URL is outside the publisher host")
        parsed = urlsplit(landing_url)
        page = LandingPage(landing_url, self.client.get(landing_url).text, self.label)
        contract = self.parse(parsed.path, page)
        if contract.embedded_bibtex is not None:
            self._embedded[landing_url] = contract.embedded_bibtex
            bibtex_url = landing_url
        elif contract.bibtex_path is not None:
            bibtex_url = same_origin(landing_url, contract.bibtex_path)
        else:
            raise PageContractChanged(f"{self.label} page has no official BibTeX")
        return SourceDocument(
            metadata=contract.metadata,
            pdf_url=same_origin(landing_url, contract.pdf_path),
            bibtex_url=bibtex_url,
            allowed_hosts=frozenset({str(parsed.hostname).casefold().rstrip(".")}),
        )

    def acquire(self, document: SourceDocument) -> AcquiredPair:
        landing_url = document.metadata.landing_url
        if document.bibtex_url == landing_url:
            if landing_url not in self._embedded:
                self.resolve(landing_url)
            text = self._embedded[landing_url]
            raw, source = text.encode("utf-8"), EMBEDDED_BIBTEX_SOURCE
        else:
            raw = self.client.get(document.bibtex_url).content
            text, source = decode_bibtex_bytes(raw)[0], "publisher_download"
        return AcquiredPair(
            document=document,
            pdf_bytes=self.client.get(document.pdf_url).content,
            bibtex_text=text,
            bibtex_bytes=raw,
            bibtex_source=source,
        )


_AAAI_PATH = re.compile(r"/index\.php/([A-Za-z0-9_-]+)/article/view/(\d+)/?")


class AaaiOjsAdapter(_OpenAccessAdapter):
    """AAAI conference, symposium, and journal proceedings on ojs.aaai.org."""

    name = "aaai-ojs"
    label = "AAAI"
    default_hosts = frozenset({"ojs.aaai.org"})

    def parse(self, path: str, page: LandingPage) -> PageContract:
        match = _AAAI_PATH.fullmatch(path)
        if not match:
            raise PageContractChanged("AAAI landing path is not an OJS article page")
        journal, article = match.groups()
        doi = normalize_doi(page.one("citation_doi", "DOI"))
        if not doi or not doi.startswith("10.1609/"):
            raise PageContractChanged("AAAI page DOI is not an AAAI DOI")
        pdf_path = page.meta_path("citation_pdf_url", "PDF metadata")
        if not re.fullmatch(rf"/index\.php/{re.escape(journal)}/article/download/{article}/\d+",
                            pdf_path):
            raise PageContractChanged("AAAI PDF URL does not match the article")
        export = f"/index.php/{journal}/citationstylelanguage/download/bibtex"
        exports = {(target, query) for target, query in page.link_targets("BibTeX")
                   if target == export and parse_qs(query).get("submissionId") == [article]}
        if len(exports) != 1:
            raise PageContractChanged("AAAI page must expose one BibTeX export for the article")
        bibtex_path, query = exports.pop()
        return PageContract(
            metadata=PaperMetadata(
                title=page.one("citation_title", "title") or "",
                authors=page.authors(),
                year=page.year("citation_date", "publication date"),
                venue=page.one("citation_journal_title", "venue") or "",
                doi=doi,
                publisher="Association for the Advancement of Artificial Intelligence",
                landing_url=page.landing_url,
                publication_type=page.one("DC.Type.articleType", "track", required=False),
            ),
            pdf_path=pdf_path,
            bibtex_path=f"{bibtex_path}?{query}",
        )


_NEURIPS_PATH = re.compile(
    r"/paper_files/paper/((?:19|20)\d{2})/hash/([0-9a-f]{32})-Abstract(-[A-Za-z_]+)?\.html"
)
# Since 2021 the page's "Bibtex" anchor points at a broken /paper_files/paper/<n>-/bibtex route;
# the same hash's official BibTeX file is served beside the PDF.
_NEURIPS_BROKEN_BIBTEX = re.compile(r"/paper_files/paper/\d+-/bibtex")


class NeuripsProceedingsAdapter(_OpenAccessAdapter):
    name = "neurips-proceedings"
    label = "NeurIPS"
    default_hosts = frozenset({"proceedings.neurips.cc"})
    publisher = "Neural Information Processing Systems Foundation"

    def parse(self, path: str, page: LandingPage) -> PageContract:
        label = self.label
        match = _NEURIPS_PATH.fullmatch(path)
        if not match:
            raise PageContractChanged(f"{label} landing path is not a proceedings abstract page")
        year, digest, track = match.group(1), match.group(2), match.group(3) or ""
        pdf_path = f"/paper_files/paper/{year}/file/{digest}-Paper{track}.pdf"
        if page.meta_path("citation_pdf_url", "PDF metadata") != pdf_path:
            raise PageContractChanged(f"{label} PDF URL does not match the paper hash")
        if any(target != pdf_path for target, _ in page.link_targets("Paper")):
            raise PageContractChanged(f"{label} paper link disagrees with the PDF metadata")
        bibtex_path = f"/paper_files/paper/{year}/file/{digest}-Bibtex.bib"
        links = page.link_targets("Bibtex")
        if len(links) != 1 or not (links[0][0] == bibtex_path
                                   or _NEURIPS_BROKEN_BIBTEX.fullmatch(links[0][0])):
            raise PageContractChanged(f"{label} page must expose one BibTeX link for the paper")
        if page.year("citation_publication_date", "publication date") != int(year):
            raise PageContractChanged(f"{label} publication year disagrees with the landing path")
        normalized_track = track.lstrip("-").casefold()
        return PageContract(
            metadata=PaperMetadata(
                title=page.one("citation_title", "title") or "",
                authors=page.authors(family_first=True),
                year=int(year),
                venue=page.first(("citation_journal_title", "citation_conference_title"), "venue"),
                doi=normalize_doi(page.one("citation_doi", "DOI", required=False)),
                publisher=self.publisher,
                landing_url=page.landing_url,
                publication_type="main" if normalized_track in {"", "conference"}
                else normalized_track.replace("_", "-"),
            ),
            pdf_path=pdf_path,
            bibtex_path=bibtex_path,
        )


class IclrProceedingsAdapter(NeuripsProceedingsAdapter):
    """ICLR papers from 2024 on proceedings.iclr.cc, which runs the NeurIPS proceedings software.

    Earlier ICLR papers exist only on OpenReview, which answers non-browser clients with a
    challenge page, so they stay manual downloads.
    """

    name = "iclr-proceedings"
    label = "ICLR"
    default_hosts = frozenset({"proceedings.iclr.cc"})
    publisher = "International Conference on Learning Representations"


_PMLR_PATH = re.compile(r"/(v\d+)/([A-Za-z0-9_-]+)\.html")


class PmlrAdapter(_OpenAccessAdapter):
    name = "pmlr"
    label = "PMLR"
    default_hosts = frozenset({"proceedings.mlr.press"})

    def parse(self, path: str, page: LandingPage) -> PageContract:
        match = _PMLR_PATH.fullmatch(path)
        if not match:
            raise PageContractChanged("PMLR landing path is not a paper page")
        volume, key = match.groups()
        pdf_path = f"/{volume}/{key}/{key}.pdf"
        if page.meta_path("citation_pdf_url", "PDF metadata") != pdf_path:
            raise PageContractChanged("PMLR PDF URL does not match the paper key")
        bibtex = page.embedded_bibtex("code#bibtex")
        entry_key = _BIBTEX_KEY.match(bibtex)
        if not entry_key or entry_key.group(1) != f"pmlr-{volume}-{key}":
            raise PageContractChanged("PMLR BibTeX entry does not match the paper key")
        return PageContract(
            metadata=PaperMetadata(
                title=page.one("citation_title", "title") or "",
                authors=page.authors(),
                year=page.year("citation_publication_date", "publication date"),
                venue=page.first(("citation_conference_title", "citation_inbook_title",
                                  "citation_journal_title"), "venue"),
                doi=None,
                publisher="PMLR",
                landing_url=page.landing_url,
                publication_type="research-article",
            ),
            pdf_path=pdf_path,
            embedded_bibtex=bibtex,
        )


# Observed layouts: /content/CVPR2023/html/…, /content/CVPR2023W/<workshop>/html/…, and the
# pre-2020 /content_CVPR_2019/html/….
_CVF_PATH = re.compile(
    r"/(content/[A-Za-z]+(?:19|20)\d{2}(?:W/[A-Za-z0-9_-]+)?|content_[A-Za-z]+_(?:19|20)\d{2})"
    r"/html/([^/]+_paper)\.html"
)


class CvfOpenAccessAdapter(_OpenAccessAdapter):
    """CVF open-access versions of CVPR, ICCV, WACV, and their workshops.

    CVF states these are identical to the accepted versions except for the watermark; the
    final IEEE Xplore version is a separate publisher artifact.
    """

    name = "cvf-open-access"
    label = "CVF"
    default_hosts = frozenset({"openaccess.thecvf.com"})

    def parse(self, path: str, page: LandingPage) -> PageContract:
        match = _CVF_PATH.fullmatch(path)
        if not match:
            raise PageContractChanged("CVF landing path is not an open-access paper page")
        prefix, stem = match.groups()
        pdf_path = f"/{prefix}/papers/{stem}.pdf"
        if page.meta_path("citation_pdf_url", "PDF metadata") != pdf_path:
            raise PageContractChanged("CVF PDF URL does not match the paper page")
        if [target for target, _ in page.link_targets("pdf")] != [pdf_path]:
            raise PageContractChanged("CVF page must expose one PDF link for the paper")
        year_match = re.search(r"(?:19|20)\d{2}", prefix)
        if year_match is None:
            raise PageContractChanged("CVF paper path must name its conference year")
        path_year = int(year_match.group())
        if page.year("citation_publication_date", "publication date") != path_year:
            raise PageContractChanged("CVF publication year disagrees with the landing path")
        workshop = "W/" in prefix
        return PageContract(
            metadata=PaperMetadata(
                title=page.one("citation_title", "title") or "",
                authors=page.authors(family_first=True),
                year=path_year,
                venue=page.one("citation_conference_title", "venue") or "",
                doi=None,
                publisher="Computer Vision Foundation",
                landing_url=page.landing_url,
                publication_type="workshop" if workshop else "main",
            ),
            pdf_path=pdf_path,
            embedded_bibtex=page.embedded_bibtex("div.bibref"),
        )


_USENIX_PATH = re.compile(r"/conference/([a-z]+)(\d{2})/presentation/[A-Za-z0-9_-]+")
_USENIX_PDF = re.compile(r"/system/files/[A-Za-z0-9_.-]+\.pdf")
_BIBTEX_URL = re.compile(r"\burl\s*=\s*\{([^{}]*)\}", re.IGNORECASE)


class UsenixAdapter(_OpenAccessAdapter):
    """Open-access papers of USENIX conferences (Security, OSDI, NSDI, ATC, FAST, and others).

    The page's BibTeX download link answers non-browser clients with a Cloudflare challenge;
    the same entry is printed on the page, and its ``url`` field must name this page.
    """

    name = "usenix"
    label = "USENIX"
    default_hosts = frozenset({"www.usenix.org"})

    def parse(self, path: str, page: LandingPage) -> PageContract:
        match = _USENIX_PATH.fullmatch(path.rstrip("/"))
        if not match:
            raise PageContractChanged("USENIX landing path is not a presentation page")
        pdf_path = page.meta_path("citation_pdf_url", "PDF metadata")
        if not _USENIX_PDF.fullmatch(pdf_path):
            raise PageContractChanged("USENIX PDF URL is not a proceedings file")
        bibtex = page.embedded_bibtex("div.bibtex-text-entry")
        named = _BIBTEX_URL.search(bibtex)
        if not named or urlsplit(named.group(1).strip()).path.rstrip("/") != path.rstrip("/"):
            raise PageContractChanged("USENIX BibTeX entry names a different presentation")
        year = page.year("citation_publication_date", "publication date")
        if year % 100 != int(match.group(2)):
            raise PageContractChanged("USENIX publication year disagrees with the conference")
        # USENIX titles carry BibTeX case-protection braces, e.g. "{SAIN}: Improving {ICS} ...".
        title = (page.one("citation_title", "title") or "").replace("{", "").replace("}", "")
        return PageContract(
            metadata=PaperMetadata(
                title=title,
                authors=page.authors(),
                year=year,
                venue=page.one("citation_conference_title", "venue") or "",
                doi=None,
                publisher="USENIX Association",
                landing_url=page.landing_url,
                publication_type="main",
            ),
            pdf_path=pdf_path,
            embedded_bibtex=bibtex,
        )


OPEN_ACCESS_ADAPTERS = (AaaiOjsAdapter, NeuripsProceedingsAdapter, IclrProceedingsAdapter,
                        PmlrAdapter, CvfOpenAccessAdapter, UsenixAdapter)
