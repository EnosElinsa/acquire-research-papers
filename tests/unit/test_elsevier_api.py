from __future__ import annotations

import json
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from acquire_research_papers.acquisition.adapters import elsevier_api
from acquire_research_papers.acquisition.adapters.elsevier_api import (
    ELSEVIER_API_HOST,
    DpapiElsevierApiKeyProvider,
    ElsevierApiError,
)
from acquire_research_papers.http import RateLimited, SafeHttpClient


def test_dpapi_provider_reads_one_key_for_exact_api_host(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="synthetic-key\n", stderr="")

    provider = DpapiElsevierApiKeyProvider(
        script=tmp_path / "read-elsevier-api-key.ps1",
        secret_path=tmp_path / "secrets.clixml",
        process_runner=run,
    )

    assert provider() == "synthetic-key"
    assert calls[0][calls[0].index("-ExpectedHost") + 1] == ELSEVIER_API_HOST
    assert "synthetic-key" not in calls[0]


def test_dpapi_provider_rejects_ambiguous_output(tmp_path: Path) -> None:
    provider = DpapiElsevierApiKeyProvider(
        script=tmp_path / "read-elsevier-api-key.ps1",
        secret_path=tmp_path / "secrets.clixml",
        process_runner=lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            0,
            stdout="first\nsecond\n",
            stderr="",
        ),
    )

    with pytest.raises(ElsevierApiError, match="could not be loaded"):
        provider()


def test_dpapi_provider_wraps_a_timed_out_secret_bridge(tmp_path: Path) -> None:
    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, timeout=30)

    provider = DpapiElsevierApiKeyProvider(
        script=tmp_path / "read-elsevier-api-key.ps1",
        secret_path=tmp_path / "secrets.clixml",
        process_runner=timeout,
    )

    with pytest.raises(ElsevierApiError, match="could not be loaded") as caught:
        provider()
    assert caught.value.phase == "api-key"


def _search_payload(*entries: dict[str, object]) -> dict[str, object]:
    return {
        "search-results": {
            "opensearch:totalResults": str(len(entries)),
            "entry": list(entries),
        }
    }


def _search_entry() -> dict[str, object]:
    return {
        "dc:title": (
            "Farmers’ cooperatives and smallholder farmers’ access to credit: "
            "Evidence from China"
        ),
        "dc:creator": "Jiang M.",
        "prism:publicationName": "Journal of Asian Economics",
        "prism:coverDate": "2024-06-01",
        "prism:doi": "10.1016/j.asieco.2024.101746",
        "pii": "S1049007824000411",
        "subtypeDescription": "Article",
    }


def _search_client(*, client: SafeHttpClient):
    assert hasattr(elsevier_api, "ElsevierSearchClient"), "ElsevierSearchClient is not implemented"
    return elsevier_api.ElsevierSearchClient(
        client=client,
        key_provider=lambda: "synthetic-key",
    )


def test_search_resolves_canonical_sciencedirect_document_from_doi(monkeypatch) -> None:
    client = SafeHttpClient(allowed_hosts={"api.elsevier.com"}, retries=0)
    calls: list[tuple[str, dict[str, str]]] = []

    def request(method, url, **kwargs):
        calls.append((url, dict(kwargs.get("headers") or {})))
        return httpx.Response(
            200,
            request=httpx.Request(method, url),
            content=json.dumps(_search_payload(_search_entry())).encode(),
        )

    monkeypatch.setattr(client._client, "request", request)
    record = _search_client(client=client).resolve(
        "https://doi.org/10.1016/j.asieco.2024.101746"
    )

    assert record.pii == "S1049007824000411"
    assert record.author_scope == "first_author"
    assert record.document.metadata.authors == ("Jiang",)
    assert record.document.metadata.authors_complete is False
    assert record.document.metadata.doi == "10.1016/j.asieco.2024.101746"
    assert record.document.metadata.landing_url == (
        "https://www.sciencedirect.com/science/article/pii/S1049007824000411"
    )
    assert record.document.pdf_url.endswith("/S1049007824000411/pdfft")
    assert "pii=S1049007824000411" in record.document.bibtex_url
    assert record.metadata_url == calls[0][0]
    assert calls[0][1]["X-ELS-APIKey"] == "synthetic-key"
    assert parse_qs(urlsplit(calls[0][0]).query)["query"] == [
        'DOI("10.1016/j.asieco.2024.101746")'
    ]


def test_search_resolves_pii_from_canonical_sciencedirect_url(monkeypatch) -> None:
    client = SafeHttpClient(allowed_hosts={"api.elsevier.com"}, retries=0)
    observed_queries: list[str] = []

    def request(method, url, **kwargs):
        observed_queries.extend(parse_qs(urlsplit(url).query)["query"])
        return httpx.Response(
            200,
            request=httpx.Request(method, url),
            content=json.dumps(_search_payload(_search_entry())).encode(),
        )

    monkeypatch.setattr(client._client, "request", request)
    _search_client(client=client).resolve(
        "https://www.sciencedirect.com/science/article/abs/pii/S1049007824000411"
    )

    assert observed_queries == ["PII(S1049007824000411)"]


def test_search_quotes_a_parenthesized_doi(monkeypatch) -> None:
    client = SafeHttpClient(allowed_hosts={"api.elsevier.com"}, retries=0)
    entry = _search_entry()
    entry["prism:doi"] = "10.1016/S0378-1127(00)00468-9"
    observed_queries: list[str] = []

    def request(method, url, **kwargs):
        observed_queries.extend(parse_qs(urlsplit(url).query)["query"])
        return httpx.Response(
            200,
            request=httpx.Request(method, url),
            content=json.dumps(_search_payload(entry)).encode(),
        )

    monkeypatch.setattr(client._client, "request", request)
    record = _search_client(client=client).resolve("10.1016/S0378-1127(00)00468-9")

    assert observed_queries == ['DOI("10.1016/s0378-1127(00)00468-9")']
    assert record.document.metadata.doi == "10.1016/s0378-1127(00)00468-9"


def test_search_preserves_compound_creator_surname(monkeypatch) -> None:
    client = SafeHttpClient(allowed_hosts={"api.elsevier.com"}, retries=0)
    entry = _search_entry()
    entry["dc:creator"] = "de Souza R."
    monkeypatch.setattr(
        client._client,
        "request",
        lambda method, url, **kwargs: httpx.Response(
            200,
            request=httpx.Request(method, url),
            content=json.dumps(_search_payload(entry)).encode(),
        ),
    )

    record = _search_client(client=client).resolve("10.1016/j.asieco.2024.101746")

    assert record.document.metadata.authors == ("de Souza",)


def test_search_rejects_noncanonical_reference_without_request(monkeypatch) -> None:
    client = SafeHttpClient(allowed_hosts={"api.elsevier.com"}, retries=0)
    monkeypatch.setattr(
        client._client,
        "request",
        lambda *args, **kwargs: pytest.fail("invalid reference must not reach Elsevier"),
    )

    with pytest.raises(ElsevierApiError) as caught:
        _search_client(client=client).resolve(
            "https://evil.example/science/article/pii/S1049007824000411"
        )
    assert caught.value.phase == "reference"


@pytest.mark.parametrize(
    "payload",
    [
        _search_payload(),
        _search_payload(_search_entry(), _search_entry()),
        _search_payload({"dc:title": "Incomplete"}),
    ],
)
def test_search_requires_one_complete_official_record(monkeypatch, payload) -> None:
    client = SafeHttpClient(allowed_hosts={"api.elsevier.com"}, retries=0)
    monkeypatch.setattr(
        client._client,
        "request",
        lambda method, url, **kwargs: httpx.Response(
            200,
            request=httpx.Request(method, url),
            content=json.dumps(payload).encode(),
        ),
    )

    with pytest.raises(ElsevierApiError) as caught:
        _search_client(client=client).resolve(
            "10.1016/j.asieco.2024.101746"
        )
    assert caught.value.phase in {"metadata-not-found", "metadata-ambiguous", "metadata"}


@pytest.mark.parametrize(("status", "phase"), [(401, "api-key"), (403, "entitlement")])
def test_search_classifies_api_access_failures(monkeypatch, status: int, phase: str) -> None:
    client = SafeHttpClient(allowed_hosts={"api.elsevier.com"}, retries=0)
    monkeypatch.setattr(
        client._client,
        "request",
        lambda method, url, **kwargs: httpx.Response(
            status,
            request=httpx.Request(method, url),
        ),
    )

    with pytest.raises(ElsevierApiError) as caught:
        _search_client(client=client).resolve("10.1016/j.asieco.2024.101746")
    assert caught.value.phase == phase


def test_search_preserves_rate_limit_classification(monkeypatch) -> None:
    client = SafeHttpClient(allowed_hosts={"api.elsevier.com"}, retries=0)
    monkeypatch.setattr(
        client._client,
        "request",
        lambda method, url, **kwargs: httpx.Response(
            429,
            request=httpx.Request(method, url),
        ),
    )

    with pytest.raises(RateLimited):
        _search_client(client=client).resolve("10.1016/j.asieco.2024.101746")
