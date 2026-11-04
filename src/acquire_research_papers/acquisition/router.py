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
    "ojs.aaai.org": "aaai-ojs",
    "proceedings.neurips.cc": "neurips-proceedings",
    "proceedings.mlr.press": "pmlr",
    "openaccess.thecvf.com": "cvf-open-access",
    "link.springer.com": "springer-link",
}

# Registrant prefixes of the supported publishers. Used only to name the publisher host of a
# DOI-only record (for --defer-host) without contacting the DOI resolver.
DOI_PREFIX_HOSTS = {
    "10.1109": "ieeexplore.ieee.org",
    "10.1145": "dl.acm.org",
    "10.1016": "www.sciencedirect.com",
    "10.18653": "aclanthology.org",
    "10.24963": "www.ijcai.org",
    "10.1609": "ojs.aaai.org",
    "10.1007": "link.springer.com",
}

_LINKINGHUB_PII = re.compile(r"/retrieve/pii/([A-Za-z0-9]+)/?")
# NeurIPS still serves the legacy papers.nips.cc host and /paper/<year>/hash/ paths; both name
# the same abstract page as the canonical /paper_files/paper/<year>/hash/ path.
_NEURIPS_HOSTS = frozenset({"papers.nips.cc", "proceedings.neurips.cc"})
_NEURIPS_LEGACY_PATH = re.compile(r"/paper/((?:19|20)\d{2})/hash/([0-9a-f]{32}-Abstract[^/]*\.html)")
# doi.org still registers plain-HTTP targets for many older IEEE DOIs (e.g. 10.1109/CVPR.2016.90).
_HTTPS_ONLY_HOSTS = frozenset({"ojs.aaai.org", "proceedings.mlr.press", "openaccess.thecvf.com",
                               "ieeexplore.ieee.org", "link.springer.com", *_NEURIPS_HOSTS})


def canonical_landing_url(url: str) -> str:
    """Rewrite a known alias of an official landing page to its canonical form without a request.

    DOI and Crossref links for Elsevier articles point at linkinghub.elsevier.com, which only
    redirects to the ScienceDirect article page for the same PII. Metadata services also
    return legacy NeurIPS addresses and plain-HTTP links to HTTPS-only archives.
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
    if host in _NEURIPS_HOSTS:
        legacy = _NEURIPS_LEGACY_PATH.fullmatch(parsed.path)
        path = (f"/paper_files/paper/{legacy.group(1)}/hash/{legacy.group(2)}"
                if legacy else parsed.path)
        return f"https://proceedings.neurips.cc{path}"
    if host in _HTTPS_ONLY_HOSTS and parsed.scheme == "http" and parsed.port is None:
        return f"https://{host}{parsed.path}" + (f"?{parsed.query}" if parsed.query else "")
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
