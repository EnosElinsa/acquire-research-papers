"""Official paper indexes of the NeurIPS proceedings, PMLR, and CVF Open Access archives.

Each candidate's ``official_url`` is the landing page that the matching acquisition adapter
accepts, so a frozen selection downloads from the same archive it was discovered in.
"""
from __future__ import annotations

import re
import threading
from collections.abc import Mapping
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from pybtex.database import parse_string
from pybtex.richtext import Text

from acquire_research_papers.acquisition.adapters._page import LandingPage, clean_text
from acquire_research_papers.acquisition.base import PageContractChanged
from acquire_research_papers.discovery.contracts import (
    CandidateMetadata,
    DiscoveryRequest,
    VenueScope,
)
from acquire_research_papers.discovery.official._index import (
    OfficialIndexProvider,
    SliceResult,
    SliceUnavailable,
    iso_date,
    normalized_title,
)
from acquire_research_papers.http import SafeHttpClient
from acquire_research_papers.models import normalize_doi


def _origin(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _aliases(series: Mapping[str, tuple[str, ...]]) -> dict[str, str]:
    return {alias: code for code, names in series.items() for alias in (code, *names)}


def _matching_title(page: LandingPage, listed: str, label: str) -> str:
    title = page.one("citation_title", "title") or ""
    if normalized_title(title) != normalized_title(listed):
        raise PageContractChanged(f"{label} index and paper titles disagree")
    return title


# --------------------------------------------------------------------------- NeurIPS

_NEURIPS_ABSTRACT = re.compile(
    r"/paper_files/paper/((?:19|20)\d{2})/hash/([0-9a-f]{32})-Abstract(?:-([A-Za-z_]+))?\.html"
)


class NeuripsIndexProvider(OfficialIndexProvider):
    """The yearly proceedings listing on proceedings.neurips.cc (main and D&B tracks)."""

    provider_id = "neurips-proceedings"
    label = "NeurIPS"
    scope_description = "NeurIPS main track and, from 2022, Datasets and Benchmarks"
    venue_aliases = _aliases({"neurips": (
        "NeurIPS", "NIPS", "Neural Information Processing Systems",
        "Conference on Neural Information Processing Systems",
        "Advances in Neural Information Processing Systems",
    )})
    publication_types = frozenset({"proceedings article", "datasets and benchmarks"})
    publishers = frozenset({"neurips", "neurips foundation", "curran associates",
                            "neural information processing systems foundation"})
    evidence_fields = frozenset({"title", "abstract", "authors", "venue", "publication_type",
                                 "track", "doi", "publication_date"})

    def __init__(
        self,
        client: SafeHttpClient | None,
        *,
        index_template: str = "https://proceedings.neurips.cc/paper_files/paper/{year}",
        production_hosts: set[str] | frozenset[str] = frozenset({"proceedings.neurips.cc"}),
        workers: int = 4,
    ) -> None:
        super().__init__(client, production_hosts=production_hosts, workers=workers)
        self.index_template = index_template

    def collect(self, archive: str, year: int, venue: VenueScope, request: DiscoveryRequest,
                seeds: Mapping[str, CandidateMetadata], result: SliceResult) -> str:
        index_url = self.index_template.format(year=year)
        soup = BeautifulSoup(self.get_text(index_url, result), "html.parser")
        entries: list[tuple[str, str, tuple[str, ...], str, str | None]] = []
        seen: set[str] = set()
        for content in soup.select("li div.paper-content"):
            result.recognized += 1
            anchor = content.find("a", href=True)
            url = urljoin(index_url, str(anchor["href"])) if anchor else ""
            match = _NEURIPS_ABSTRACT.fullmatch(urlsplit(url).path)
            if anchor is None or not match or int(match.group(1)) != year or url in seen:
                result.issue("proceedings-index", "page_contract_changed")
                continue
            seen.add(url)
            track = (match.group(3) or "").replace("_", " ")
            main = track.casefold() in {"", "conference"}
            publication_type = "proceedings-article" if main else track.casefold().replace(" ", "-")
            if self.wants_type(publication_type, request):
                listed_authors = content.select_one("span.paper-authors")
                authors = tuple(name.strip() for name in
                                (listed_authors.get_text(" ", strip=True) if listed_authors else "")
                                .split(",") if name.strip())
                entries.append((url, anchor.get_text(" ", strip=True), authors, publication_type,
                                "Main Conference" if main else track))

        def fetch_one(entry: tuple[str, str, tuple[str, ...], str, str | None]) -> CandidateMetadata:
            url, listed, listed_authors, publication_type, track = entry
            if url in seeds:
                return seeds[url]
            page = LandingPage(url, self.get_text(url, result), self.label)
            abstract = page.soup.select_one(".paper-abstract")
            # A few paper pages omit author tags; the listing still names the authors.
            authors = (page.authors(family_first=True) if page.values("citation_author")
                       else listed_authors)
            return self.candidate(
                title=_matching_title(page, listed, self.label), year=year, venue=venue,
                url=url, index_url=index_url, authors=authors,
                abstract=clean_text(abstract.get_text(" ")) if abstract else "",
                doi=normalize_doi(page.one("citation_doi", "DOI", required=False)),
                publication_type=publication_type, track=track,
                publication_date=iso_date(
                    page.one("citation_publication_date", "publication date", required=False)),
            )

        self.fetch_details(entries, fetch_one, result)
        return index_url


# --------------------------------------------------------------------------- PMLR

_PMLR_SERIES = {
    "ICML": ("International Conference on Machine Learning",),
    "AISTATS": ("International Conference on Artificial Intelligence and Statistics",
                "Artificial Intelligence and Statistics"),
    "COLT": ("Conference on Learning Theory",),
    "UAI": ("Conference on Uncertainty in Artificial Intelligence",
            "Uncertainty in Artificial Intelligence"),
    "CoRL": ("Conference on Robot Learning",),
    "ALT": ("Algorithmic Learning Theory", "International Conference on Algorithmic Learning Theory"),
    "ACML": ("Asian Conference on Machine Learning",),
    "L4DC": ("Learning for Dynamics and Control", "Learning for Dynamics and Control Conference"),
    "CLeaR": ("Conference on Causal Learning and Reasoning", "Causal Learning and Reasoning"),
}
_PMLR_VOLUME_LINK = re.compile(r"/?(v\d+)/?")
_PMLR_ENTRY = re.compile(r"(?m)^@InProceedings\{")
_PMLR_KEY = re.compile(r"pmlr-(v\d+)-([A-Za-z0-9_-]+)")


def _latex_text(value: str) -> str:
    try:
        return clean_text(str(Text.from_latex(value)))
    except Exception:  # noqa: BLE001 - pybtex raises varied errors on unusual markup
        return clean_text(value.replace("{", "").replace("}", ""))


class PmlrIndexProvider(OfficialIndexProvider):
    """PMLR volumes of major ML conferences, read from each volume's official BibTeX file."""

    provider_id = "pmlr"
    label = "PMLR"
    scope_description = "PMLR main-conference volumes: " + ", ".join(_PMLR_SERIES)
    acquisition = "official_pair_page_embedded_bibtex"
    venue_aliases = _aliases(_PMLR_SERIES)
    publishers = frozenset({"pmlr", "proceedings of machine learning research", "jmlr"})
    evidence_fields = frozenset({"title", "abstract", "authors", "venue", "publication_type"})

    def __init__(
        self,
        client: SafeHttpClient | None,
        *,
        index_url: str = "https://proceedings.mlr.press/",
        production_hosts: set[str] | frozenset[str] = frozenset({"proceedings.mlr.press"}),
    ) -> None:
        super().__init__(client, production_hosts=production_hosts, workers=1)
        self.index_url = index_url
        self._volumes: list[tuple[str, str]] | None = None
        self._lock = threading.Lock()

    def volumes(self, result: SliceResult) -> list[tuple[str, str]]:
        """(volume, title) pairs from the PMLR front page, read once per provider."""
        with self._lock:
            if self._volumes is None:
                soup = BeautifulSoup(self.get_text(self.index_url, result), "html.parser")
                found = []
                for anchor in soup.find_all("a", href=True):
                    match = _PMLR_VOLUME_LINK.fullmatch(str(anchor["href"]))
                    item = anchor.find_parent("li")
                    if match and item is not None:
                        text = re.sub(r"^Volume\s+\d+\s*", "", item.get_text(" ", strip=True))
                        found.append((match.group(1), text))
                if not found:
                    raise PageContractChanged("PMLR front page lists no volumes")
                self._volumes = found
            return self._volumes

    def collect(self, archive: str, year: int, venue: VenueScope, request: DiscoveryRequest,
                seeds: Mapping[str, CandidateMetadata], result: SliceResult) -> str:
        # "Proceedings of ICML 2023", "ICML 2016 Proceedings", "CoRL 2019"; workshop
        # volumes such as "GRaM at ICML 2024" never match.
        title = re.compile(rf"(?:Proceedings of (?:the )?)?{re.escape(archive)} {year}(?: Proceedings)?",
                           re.IGNORECASE)
        volumes = [volume for volume, text in self.volumes(result) if title.fullmatch(text)]
        if not volumes:
            raise SliceUnavailable(f"PMLR has no {archive} {year} proceedings volume")
        origin = _origin(self.index_url)
        for volume in volumes:
            bibliography = self.get_text(f"{origin}/{volume}/assets/bib/bibliography.bib", result)
            for chunk in _PMLR_ENTRY.split(bibliography)[1:]:
                result.recognized += 1
                try:
                    result.candidates.append(
                        self._entry("@InProceedings{" + chunk.strip(), volume, year, venue, origin))
                except Exception:  # noqa: BLE001 - pybtex parse errors share no common base
                    # One malformed entry costs that paper, never the volume.
                    result.issue("proceedings-index", "page_contract_changed")
        return f"{origin}/{volumes[0]}/"

    def _entry(self, text: str, volume: str, year: int, venue: VenueScope,
               origin: str) -> CandidateMetadata:
        bibliography = parse_string(text, "bibtex")
        if len(bibliography.entries) != 1:
            raise PageContractChanged("PMLR bibliography chunk is not one entry")
        key, entry = next(iter(bibliography.entries.items()))
        match = _PMLR_KEY.fullmatch(key)
        if not match or match.group(1) != volume:
            raise PageContractChanged("PMLR entry key does not name the volume")
        paper = match.group(2)
        path = f"/{volume}/{paper}.html"
        listed = entry.fields.get("url")
        if listed and urlsplit(str(listed)).path != path:
            raise PageContractChanged("PMLR entry URL does not match its key")
        if str(entry.fields.get("year", "")).strip() != str(year):
            raise PageContractChanged("PMLR entry year disagrees with the volume")
        authors = tuple(
            _latex_text(" ".join(str(part) for part in (*person.first_names, *person.middle_names,
                                                          *person.prelast_names, *person.last_names,
                                                          *person.lineage_names)))
            for person in entry.persons.get("author", ())
        )
        return self.candidate(
            title=_latex_text(str(entry.fields.get("title", ""))), year=year, venue=venue,
            url=f"{origin}{path}", index_url=f"{origin}/{volume}/", authors=authors,
            abstract=_latex_text(str(entry.fields.get("abstract", ""))),
        )


# --------------------------------------------------------------------------- CVF Open Access

_CVF_SERIES = {
    "CVPR": ("IEEE/CVF Conference on Computer Vision and Pattern Recognition",
             "Conference on Computer Vision and Pattern Recognition",
             "Computer Vision and Pattern Recognition",
             "IEEE Conference on Computer Vision and Pattern Recognition"),
    "ICCV": ("IEEE/CVF International Conference on Computer Vision",
             "International Conference on Computer Vision",
             "IEEE International Conference on Computer Vision"),
    "WACV": ("IEEE/CVF Winter Conference on Applications of Computer Vision",
             "Winter Conference on Applications of Computer Vision"),
}


class CvfIndexProvider(OfficialIndexProvider):
    """CVF Open Access listings of the CVPR, ICCV, and WACV main conferences."""

    provider_id = "cvf-open-access"
    label = "CVF"
    scope_description = "CVF open-access versions of CVPR, ICCV, and WACV main-conference papers"
    acquisition = "open_access_version_page_embedded_bibtex"
    venue_aliases = _aliases(_CVF_SERIES)
    publishers = frozenset({"cvf", "computer vision foundation", "thecvf", "ieee/cvf"})
    evidence_fields = frozenset({"title", "abstract", "authors", "venue", "publication_type"})

    def __init__(
        self,
        client: SafeHttpClient | None,
        *,
        origin: str = "https://openaccess.thecvf.com",
        production_hosts: set[str] | frozenset[str] = frozenset({"openaccess.thecvf.com"}),
        workers: int = 4,
    ) -> None:
        super().__init__(client, production_hosts=production_hosts, workers=workers)
        self.origin = origin.rstrip("/")

    @staticmethod
    def _listing(soup: BeautifulSoup, page_url: str, paper: re.Pattern[str],
                 result: SliceResult, seen: set[str]) -> list[tuple[str, str]]:
        entries = []
        for heading in soup.select("dt.ptitle"):
            result.recognized += 1
            anchor = heading.find("a", href=True)
            url = urljoin(page_url, str(anchor["href"])) if anchor else ""
            if anchor is None or not paper.fullmatch(urlsplit(url).path):
                result.issue("proceedings-index", "page_contract_changed")
                continue
            if url not in seen:
                seen.add(url)
                entries.append((url, anchor.get_text(" ", strip=True)))
        return entries

    def collect(self, archive: str, year: int, venue: VenueScope, request: DiscoveryRequest,
                seeds: Mapping[str, CandidateMetadata], result: SliceResult) -> str:
        base = f"{self.origin}/{archive}{year}"
        paper = re.compile(
            rf"/(?:content/{archive}{year}|content_{archive}_{year})/html/[^/]+_paper\.html")
        index_url = f"{base}?day=all"
        seen: set[str] = set()
        entries = self._listing(BeautifulSoup(self.get_text(index_url, result), "html.parser"),
                                index_url, paper, result, seen)
        if not result.recognized:
            # Before 2021 CVF split each conference into per-day pages.
            front = BeautifulSoup(self.get_text(base, result), "html.parser")
            days = sorted({urljoin(base, str(anchor["href"])) for anchor in front.find_all("a", href=True)
                           if re.fullmatch(rf"{archive}{year}\.py\?day=\d{{4}}-\d{{2}}-\d{{2}}",
                                           str(anchor["href"]))})
            if not days:
                raise SliceUnavailable(f"CVF lists no {archive} {year} papers")
            for day in days:
                entries.extend(self._listing(
                    BeautifulSoup(self.get_text(day, result), "html.parser"), day, paper, result,
                    seen))
            index_url = base

        def fetch_one(entry: tuple[str, str]) -> CandidateMetadata:
            url, listed = entry
            if url in seeds:
                return seeds[url]
            page = LandingPage(url, self.get_text(url, result), self.label)
            if page.year("citation_publication_date", "publication date") != year:
                raise PageContractChanged("CVF paper year disagrees with the listing")
            abstract = page.soup.select_one("div#abstract")
            return self.candidate(
                title=_matching_title(page, listed, self.label), year=year, venue=venue, url=url,
                index_url=index_url, authors=page.authors(family_first=True),
                abstract=clean_text(abstract.get_text(" ")) if abstract else "",
            )

        if self.wants_type("proceedings-article", request):
            self.fetch_details(entries, fetch_one, result)
        return index_url


ARCHIVE_INDEX_PROVIDERS = (NeuripsIndexProvider, PmlrIndexProvider, CvfIndexProvider)
