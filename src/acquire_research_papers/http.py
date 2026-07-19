from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from urllib.parse import urljoin, urlsplit

import httpx


class HostBoundaryError(ValueError):
    """A request or redirect escaped the adapter's approved hosts."""


class HttpStatusError(RuntimeError):
    def __init__(self, status_code: int, url: str) -> None:
        super().__init__(f"HTTP {status_code} for {url}")
        self.status_code = status_code
        self.url = url


class RateLimited(HttpStatusError):
    """A provider explicitly requested that acquisition stop."""


class NetworkTransient(RuntimeError):
    """Bounded connection retries were exhausted."""


_SENSITIVE_HEADERS = {
    "authorization",
    "cookie",
    "proxy-authorization",
    "x-api-key",
    "api-key",
}


class SafeHttpClient:
    def __init__(
        self,
        *,
        allowed_hosts: set[str] | frozenset[str],
        timeout: float = 30.0,
        max_redirects: int = 5,
        retries: int = 2,
        sleeper: Callable[[float], None] = time.sleep,
        user_agent: str = "acquire-research-papers/0.1.0",
    ) -> None:
        self.allowed_hosts = frozenset(host.casefold().rstrip(".") for host in allowed_hosts)
        self.max_redirects = max_redirects
        self.retries = retries
        self._sleeper = sleeper
        self._client = httpx.Client(
            follow_redirects=False,
            timeout=httpx.Timeout(timeout),
            headers={"User-Agent": user_agent},
        )

    def close(self) -> None:
        self._client.close()

    def _hostname(self, url: str) -> str:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise HostBoundaryError(f"unsupported request URL: {url}")
        hostname = parsed.hostname.casefold().rstrip(".")
        if hostname not in self.allowed_hosts:
            raise HostBoundaryError(f"host is outside adapter boundary: {hostname}")
        return hostname

    def _request_with_retries(
        self,
        url: str,
        headers: Mapping[str, str] | None,
    ) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = self._client.get(url, headers=headers)
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_error = exc
                if attempt == self.retries:
                    raise NetworkTransient(f"network retries exhausted for {url}") from exc
                self._sleeper(0.25 * (2**attempt))
                continue
            if response.status_code == 429:
                raise RateLimited(429, url)
            if 500 <= response.status_code <= 599:
                if attempt == self.retries:
                    raise HttpStatusError(response.status_code, url)
                self._sleeper(0.25 * (2**attempt))
                continue
            if response.status_code >= 400:
                raise HttpStatusError(response.status_code, url)
            return response
        raise NetworkTransient(f"network retries exhausted for {url}") from last_error

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        current_url = url
        current_host = self._hostname(current_url)
        current_headers = dict(headers or {})
        for redirect_count in range(self.max_redirects + 1):
            response = self._request_with_retries(current_url, current_headers)
            if response.status_code not in {301, 302, 303, 307, 308}:
                return response
            if redirect_count == self.max_redirects:
                raise HttpStatusError(response.status_code, current_url)
            location = response.headers.get("Location")
            if not location:
                raise HttpStatusError(response.status_code, current_url)
            target_url = urljoin(current_url, location)
            target_host = self._hostname(target_url)
            if target_host != current_host:
                current_headers = {
                    name: value
                    for name, value in current_headers.items()
                    if name.casefold() not in _SENSITIVE_HEADERS
                }
            current_url = target_url
            current_host = target_host
        raise AssertionError("redirect loop escaped its bound")
