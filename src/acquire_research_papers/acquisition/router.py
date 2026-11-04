from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import urlsplit

from acquire_research_papers.acquisition.base import SourceAdapter


_DEFAULT_HOST_NAMES = {
    "aclanthology.org": "acl-anthology",
    "www.ijcai.org": "ijcai-proceedings",
    "ieeexplore.ieee.org": "ieee-xplore",
    "dl.acm.org": "acm-dl",
    "www.sciencedirect.com": "sciencedirect",
}

# Registrant prefixes of the supported publishers. Used only to name the publisher host of a
# DOI-only record (for --defer-host) without contacting the DOI resolver.
DOI_PREFIX_HOSTS = {
    "10.1109": "ieeexplore.ieee.org",
    "10.1145": "dl.acm.org",
    "10.1016": "www.sciencedirect.com",
    "10.18653": "aclanthology.org",
    "10.24963": "www.ijcai.org",
}

_LINKINGHUB_PII = re.compile(r"/retrieve/pii/([A-Za-z0-9]+)/?")


def canonical_landing_url(url: str) -> str:
    """Rewrite a known publisher link resolver to its canonical landing page without a request.

    DOI and Crossref links for Elsevier articles point at linkinghub.elsevier.com, which only
    redirects to the ScienceDirect article page for the same PII.
    """
    try:
        parsed = urlsplit(url)
    except ValueError:
        return url
    host = (parsed.hostname or "").casefold().rstrip(".")
    if host == "linkinghub.elsevier.com":
        match = _LINKINGHUB_PII.fullmatch(parsed.path)
        if match:
            return f"https://www.sciencedirect.com/science/article/pii/{match.group(1).upper()}"
    return url


def doi_publisher_host(doi: str | None) -> str | None:
    prefix = str(doi or "").strip().split("/", 1)[0].casefold()
    return DOI_PREFIX_HOSTS.get(prefix)


class AdapterRouter:
    def __init__(
        self,
        host_names: dict[str, str] | None = None,
        adapters: Iterable[SourceAdapter] = (),
    ) -> None:
        self._host_names = {
            host.casefold().rstrip("."): name for host, name in (host_names or {}).items()
        }
        self._adapters = {adapter.name: adapter for adapter in adapters}

    @classmethod
    def with_defaults(cls, adapters: Iterable[SourceAdapter] = ()) -> AdapterRouter:
        return cls(dict(_DEFAULT_HOST_NAMES), adapters)

    def name_for(self, url: str) -> str | None:
        hostname = urlsplit(url).hostname
        if not hostname:
            return None
        return self._host_names.get(hostname.casefold().rstrip("."))

    def adapter_for(self, url: str) -> SourceAdapter | None:
        name = self.name_for(url)
        return self._adapters.get(name) if name else None
