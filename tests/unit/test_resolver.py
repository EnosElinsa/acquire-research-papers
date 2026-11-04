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


def test_unsupported_publisher_names_its_host() -> None:
    from acquire_research_papers.resolver import UnsupportedPublisher

    with pytest.raises(UnsupportedPublisher, match="link.springer.com") as error:
        Resolver.empty().resolve("https://link.springer.com/article/10.1007/example")
    assert error.value.hostname == "link.springer.com"


def test_doi_resolver_retries_server_errors_with_backoff(httpserver) -> None:
    httpserver.expect_ordered_request("/10.1234/test.1").respond_with_data("", status=503)
    httpserver.expect_ordered_request("/10.1234/test.1").respond_with_data(
        "", status=302, headers={"Location": "https://publisher.example/article/1"}
    )
    pauses: list[float] = []
    resolver = DoiRedirectResolver(endpoint=httpserver.url_for("/"), sleeper=pauses.append)
    assert resolver.resolve("10.1234/test.1") == "https://publisher.example/article/1"
    assert pauses == [1.0]


def test_doi_resolver_network_failure_is_transient(monkeypatch) -> None:
    import httpx

    from acquire_research_papers.http import NetworkTransient

    def unreachable(self, url, **kwargs):
        raise httpx.ConnectTimeout("doi.org timed out")

    monkeypatch.setattr(httpx.Client, "get", unreachable)
    pauses: list[float] = []
    resolver = DoiRedirectResolver(retries=2, sleeper=pauses.append)
    with pytest.raises(NetworkTransient):
        resolver.resolve("10.1234/test.1")
    assert pauses == [1.0, 2.0]


def test_elsevier_link_resolver_maps_to_the_manual_sciencedirect_route() -> None:
    from acquire_research_papers.acquisition.adapters.sciencedirect import ScienceDirectAdapter
    from acquire_research_papers.acquisition.base import AccessRequired
    from acquire_research_papers.acquisition.router import AdapterRouter

    class LinkingHub:
        def resolve(self, doi: str) -> str:
            return "https://linkinghub.elsevier.com/retrieve/pii/S0140366421001234"

    resolver = Resolver(
        AdapterRouter.with_defaults([ScienceDirectAdapter.for_production()]),
        doi_resolver=LinkingHub(),
    )
    with pytest.raises(AccessRequired, match="manual-fetch"):
        resolver.resolve("10.1016/j.comcom.2021.01.001")
