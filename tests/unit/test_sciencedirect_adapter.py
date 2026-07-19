import pytest

from acquire_research_papers.acquisition.adapters.sciencedirect import ScienceDirectAdapter
from acquire_research_papers.acquisition.base import AccessRequired, NotOfficial, PageContractChanged
from acquire_research_papers.http import SafeHttpClient


def test_sciencedirect_requires_manual_handoff_without_requesting_the_page(monkeypatch) -> None:
    client = SafeHttpClient(allowed_hosts={"www.sciencedirect.com"}, retries=0)
    monkeypatch.setattr(
        client._client,
        "request",
        lambda *args, **kwargs: pytest.fail("manual-only ScienceDirect must not request the page"),
    )
    adapter = ScienceDirectAdapter(client=client)

    with pytest.raises(AccessRequired, match="manual-fetch"):
        adapter.resolve(
            "https://www.sciencedirect.com/science/article/pii/S1049007824000411"
        )


def test_sciencedirect_manual_guard_rejects_nonofficial_host() -> None:
    adapter = ScienceDirectAdapter(
        client=SafeHttpClient(allowed_hosts={"www.sciencedirect.com"}, retries=0)
    )

    with pytest.raises(NotOfficial):
        adapter.resolve("https://www.sciencedirect.com.evil.example/science/article/pii/TEST")


def test_sciencedirect_manual_guard_requires_canonical_pii_path() -> None:
    adapter = ScienceDirectAdapter(
        client=SafeHttpClient(allowed_hosts={"www.sciencedirect.com"}, retries=0)
    )

    with pytest.raises(PageContractChanged):
        adapter.resolve("https://www.sciencedirect.com/search?qs=paper")
