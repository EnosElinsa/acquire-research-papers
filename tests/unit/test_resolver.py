import pytest

from acquire_research_papers.resolver import AmbiguousInput, DoiRedirectResolver, Resolver


def test_title_only_input_is_rejected_without_canonical_discovery() -> None:
    resolver = Resolver.empty()
    with pytest.raises(AmbiguousInput, match="title"):
        resolver.acquire("A title that could identify several works")


def test_unsupported_url_is_rejected() -> None:
    resolver = Resolver.empty()
    with pytest.raises(AmbiguousInput, match="supported official"):
        resolver.acquire("https://example.org/paper")


def test_doi_resolver_returns_first_official_landing_redirect(httpserver) -> None:
    httpserver.expect_request("/10.1234/test.1").respond_with_data(
        "",
        status=302,
        headers={"Location": "https://publisher.example/article/1"},
    )
    resolver = DoiRedirectResolver(endpoint=httpserver.url_for("/"))
    assert resolver.resolve("10.1234/test.1") == "https://publisher.example/article/1"


def test_doi_resolver_rejects_non_http_location(httpserver) -> None:
    httpserver.expect_request("/10.1234/test.1").respond_with_data(
        "",
        status=302,
        headers={"Location": "file:///sensitive"},
    )
    resolver = DoiRedirectResolver(endpoint=httpserver.url_for("/"))
    with pytest.raises(AmbiguousInput, match="redirect"):
        resolver.resolve("10.1234/test.1")
