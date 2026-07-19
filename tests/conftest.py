from __future__ import annotations

from dataclasses import dataclass

import pytest
from pytest_httpserver import HTTPServer

from acquire_research_papers.http import SafeHttpClient


@dataclass
class FixtureServer:
    server: HTTPServer

    @property
    def host(self) -> str:
        return self.server.host

    @property
    def client(self) -> SafeHttpClient:
        return SafeHttpClient(allowed_hosts={self.host})

    def url(self, path: str) -> str:
        return self.server.url_for(path)

    def serve_text(self, path: str, value: str, content_type: str = "text/html") -> None:
        self.server.expect_request(path).respond_with_data(value, content_type=content_type)

    def serve_bytes(self, path: str, value: bytes, content_type: str) -> None:
        self.server.expect_request(path).respond_with_data(value, content_type=content_type)


@pytest.fixture
def fixture_server(httpserver: HTTPServer) -> FixtureServer:
    return FixtureServer(httpserver)
