from acquire_research_papers.acquisition.router import AdapterRouter


def test_router_uses_exact_hostname() -> None:
    router = AdapterRouter.with_defaults()
    assert router.name_for("https://aclanthology.org/2025.acl-long.1/") == "acl-anthology"
    assert router.name_for("https://ieeexplore.ieee.org/document/1") == "ieee-xplore"
    assert router.name_for("https://aclanthology.org.evil.example/paper") is None


def test_router_recognizes_initial_provider_set() -> None:
    router = AdapterRouter.with_defaults()
    assert router.name_for("https://www.ijcai.org/proceedings/2025/1") == "ijcai-proceedings"
    assert router.name_for("https://dl.acm.org/doi/10.1145/1") == "acm-dl"
    assert router.name_for("https://www.sciencedirect.com/science/article/pii/X") == "sciencedirect"
