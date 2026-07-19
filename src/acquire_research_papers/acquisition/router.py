from __future__ import annotations

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
