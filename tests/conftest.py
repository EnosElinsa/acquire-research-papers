from __future__ import annotations

from dataclasses import dataclass

import pytest
from pytest_httpserver import HTTPServer

from acquire_research_papers.acquisition.base import AcquiredPair, SourceDocument
from acquire_research_papers.http import SafeHttpClient
from acquire_research_papers.models import PaperMetadata


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


@pytest.fixture
def verified_pair() -> AcquiredPair:
    metadata = PaperMetadata(
        title="Verified Paper",
        authors=("Ada Lovelace",),
        year=2026,
        venue="Test Venue",
        doi="10.1109/test.1",
        publisher="Test Publisher",
        landing_url="https://publisher.example/paper",
    )
    document = SourceDocument(
        metadata=metadata,
        pdf_url="https://publisher.example/paper.pdf",
        bibtex_url="https://publisher.example/paper.bib",
        allowed_hosts=frozenset({"publisher.example"}),
    )
    return AcquiredPair(
        document=document,
        pdf_bytes=b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n",
        bibtex_text=(
            "@article{k,title={Verified Paper},author={Lovelace, Ada},year={2026},"
            "journal={Test Venue},doi={10.1109/test.1}}"
        ),
    )
