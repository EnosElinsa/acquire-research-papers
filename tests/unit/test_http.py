import pytest

from acquire_research_papers.http import HostBoundaryError, RateLimited, SafeHttpClient


def test_redirect_outside_allowed_hosts_is_rejected(httpserver) -> None:
    httpserver.expect_request("/paper").respond_with_data(
        "", status=302, headers={"Location": "https://attacker.example/capture"}
    )
    client = SafeHttpClient(allowed_hosts={httpserver.host})
    with pytest.raises(HostBoundaryError):
        client.get(httpserver.url_for("/paper"))


def test_same_host_relative_redirect_is_followed(httpserver) -> None:
    httpserver.expect_ordered_request("/paper").respond_with_data(
        "", status=302, headers={"Location": "/paper.pdf"}
    )
    httpserver.expect_ordered_request("/paper.pdf").respond_with_data(
        "%PDF-1.7", content_type="application/pdf"
    )
    client = SafeHttpClient(allowed_hosts={httpserver.host})
    response = client.get(httpserver.url_for("/paper"))
    assert response.url.path == "/paper.pdf"


def test_server_error_is_retried_twice(httpserver) -> None:
    httpserver.expect_ordered_request("/flaky").respond_with_data("wait", status=503)
    httpserver.expect_ordered_request("/flaky").respond_with_data("wait", status=503)
    httpserver.expect_ordered_request("/flaky").respond_with_data("ok", status=200)
    client = SafeHttpClient(allowed_hosts={httpserver.host}, sleeper=lambda _: None)
    assert client.get(httpserver.url_for("/flaky")).text == "ok"


def test_rate_limit_is_classified_without_retry(httpserver) -> None:
    httpserver.expect_request("/limited").respond_with_data("slow down", status=429)
    client = SafeHttpClient(allowed_hosts={httpserver.host})
    with pytest.raises(RateLimited):
        client.get(httpserver.url_for("/limited"))
