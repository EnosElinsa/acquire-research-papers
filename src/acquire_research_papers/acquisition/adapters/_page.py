"""Shared reading of official landing pages: citation meta tags and exact page contracts.

Adapters compare only URL paths taken from a page and always rebuild request URLs on the
landing page's own origin, so a page can never redirect acquisition to another host.
"""
from __future__ import annotations

import html as html_lib
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from acquire_research_papers.acquisition.base import PageContractChanged

_YEAR = re.compile(r"(?:19|20)\d{2}")


def clean_text(value: str) -> str:
    return " ".join(html_lib.unescape(value).split())


def given_family(name: str) -> str:
    """Turn a "Family, Given" meta author into "Given Family"; other forms are kept."""
    parts = [part.strip() for part in name.split(",")]
    if len(parts) == 2 and all(parts):
        return f"{parts[1]} {parts[0]}"
    return name


def same_origin(landing_url: str, path: str) -> str:
    parsed = urlsplit(landing_url)
    return f"{parsed.scheme}://{parsed.netloc}{path}"


class LandingPage:
    def __init__(self, landing_url: str, html: str, label: str) -> None:
        self.landing_url = landing_url
        self.soup = BeautifulSoup(html, "html.parser")
        self.label = label

    def values(self, name: str) -> list[str]:
        pattern = re.compile(f"^{re.escape(name)}$", re.IGNORECASE)
        found = (clean_text(str(tag.get("content", "")))
                 for tag in self.soup.find_all("meta", attrs={"name": pattern}))
        return [value for value in found if value]

    def one(self, name: str, label: str, *, required: bool = True) -> str | None:
        found = self.values(name)
        if len(found) > 1:
            raise PageContractChanged(f"{self.label} page has ambiguous {label}")
        if not found:
            if required:
                raise PageContractChanged(f"{self.label} page has no {label}")
            return None
        return found[0]

    def first(self, names: tuple[str, ...], label: str) -> str:
        for name in names:
            value = self.one(name, label, required=False)
            if value:
                return value
        raise PageContractChanged(f"{self.label} page has no {label}")

    def year(self, name: str, label: str) -> int:
        match = _YEAR.search(self.one(name, label) or "")
        if not match:
            raise PageContractChanged(f"{self.label} {label} has no four-digit year")
        return int(match.group())

    def authors(self, *, family_first: bool = False) -> tuple[str, ...]:
        authors = tuple(given_family(name) if family_first else name
                        for name in self.values("citation_author"))
        if not authors:
            raise PageContractChanged(f"{self.label} page has no authors")
        return authors

    def meta_path(self, name: str, label: str) -> str:
        return urlsplit(urljoin(self.landing_url, self.one(name, label) or "")).path

    def link_targets(self, text: str) -> list[tuple[str, str]]:
        """(path, query) of same-host anchors whose visible text equals ``text``."""
        host = (urlsplit(self.landing_url).hostname or "").casefold()
        targets = []
        for anchor in self.soup.find_all("a", href=True):
            if anchor.get_text(" ", strip=True).casefold() != text.casefold():
                continue
            resolved = urlsplit(urljoin(self.landing_url, str(anchor["href"])))
            if (resolved.hostname or "").casefold() == host:
                targets.append((resolved.path, resolved.query))
        return targets

    def embedded_bibtex(self, selector: str) -> str:
        """The single BibTeX entry the publisher prints on its page, as displayed text."""
        blocks = [element.get_text() for element in self.soup.select(selector)
                  if element.get_text().strip().startswith("@")]
        if len(blocks) != 1:
            raise PageContractChanged(f"{self.label} page must show exactly one BibTeX entry")
        # Only the page layout around the entry is trimmed; the entry text is kept as shown.
        return blocks[0].strip() + "\n"
