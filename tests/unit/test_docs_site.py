"""Structure of the English and Chinese documentation sites (mkdocs.yml, mkdocs.zh.yml).

CI builds both with `mkdocs build --strict`, which checks links and anchors; these tests keep
the two page trees in step without needing MkDocs installed.
"""
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
SITE_URL = "https://enoselinsa.github.io/acquire-research-papers/"


class _ConfigLoader(yaml.SafeLoader):
    """Reads mkdocs.yml without constructing its `!!python/...` slugify object."""


_ConfigLoader.add_multi_constructor("tag:yaml.org,2002:python/", lambda *_args: None)


def _config(name: str) -> dict[str, Any]:
    return yaml.load((ROOT / name).read_text(encoding="utf-8"), Loader=_ConfigLoader)


def _nav_pages(nav: list[Any]) -> list[str]:
    pages: list[str] = []
    for entry in nav:
        for value in entry.values():
            pages.extend(_nav_pages(value) if isinstance(value, list) else [value])
    return pages


def test_both_languages_have_the_same_pages_so_the_selector_keeps_the_page() -> None:
    english = {path.name for path in (ROOT / "docs-site/en").glob("*.md")}
    chinese = {path.name for path in (ROOT / "docs-site/zh").glob("*.md")}

    assert english == chinese
    assert "index.md" in english


def test_every_page_is_in_both_navigations_in_the_same_order() -> None:
    english = _config("mkdocs.yml")
    chinese = _config("mkdocs.zh.yml")
    pages = sorted(path.name for path in (ROOT / "docs-site/en").glob("*.md"))

    assert sorted(_nav_pages(english["nav"])) == pages
    assert _nav_pages(chinese["nav"]) == _nav_pages(english["nav"])
    assert chinese["INHERIT"] == "mkdocs.yml"
    assert (english["docs_dir"], english["site_dir"]) == ("docs-site/en", "site")
    assert (chinese["docs_dir"], chinese["site_dir"]) == ("docs-site/zh", "site/zh")
    assert english["site_url"] == SITE_URL
    assert chinese["site_url"] == SITE_URL + "zh/"


def test_readmes_link_the_documentation_site() -> None:
    assert SITE_URL in (ROOT / "README.md").read_text(encoding="utf-8")
    assert SITE_URL + "zh/" in (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
