from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from acquire_research_papers.acquisition.adapters.springer import (
    CITATION_HOST,
    COOKIE_HOST,
    SPRINGER_HOST,
    SpringerLinkAdapter,
)
from acquire_research_papers.acquisition.base import PageContractChanged
from acquire_research_papers.acquisition.router import canonical_landing_url, doi_publisher_host
from acquire_research_papers.cli import Application, run_cli
from acquire_research_papers.http import SafeHttpClient

PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
ARTICLE_DOI = "10.1007/s10994-026-00001-x"
CHAPTER_DOI = "10.1007/978-3-031-00001-1_7"


def article_page(*, has_access: str = "Y", pdf_doi: str = ARTICLE_DOI) -> str:
    return f"""<html><head>
<meta name="citation_title" content="A Verified Springer Article">
<meta name="citation_author" content="Lovelace, Ada">
<meta name="citation_author" content="Turing, Alan">
<meta name="citation_journal_title" content="Machine Learning">
<meta name="citation_publication_date" content="2026/03">
<meta name="citation_online_date" content="2025/11/24">
<meta name="citation_doi" content="{ARTICLE_DOI}">
<meta name="citation_pdf_url" content="https://link.springer.com/content/pdf/{pdf_doi}.pdf">
<script>window.dataLayer = [{{"Open Access":"N","hasAccess":"{has_access}"}}]</script>
</head><body>
<a href="/content/pdf/{ARTICLE_DOI}.pdf">Download PDF</a>
<a href="https://citation-needed.springer.com/v2/references/{ARTICLE_DOI}?format=refman&amp;flavour=citation">Download citation</a>
</body></html>"""


def chapter_page() -> str:
    return f"""<html><head>
<meta name="citation_title" content="Learning Depth from&#160;Focus">
<meta name="citation_author" content="Lovelace, Ada">
<meta name="citation_inbook_title" content="Computer Vision &#8211; ECCV 2026">
<meta name="citation_conference_title" content="European Conference on Computer Vision">
<meta name="citation_publication_date" content="2026">
<meta name="citation_doi" content="{CHAPTER_DOI}">
<meta name="citation_pdf_url" content="https://link.springer.com/content/pdf/{CHAPTER_DOI}.pdf">
<script>window.dataLayer = [{{"Open Access":"Y","hasAccess":"Y"}}]</script>
</head><body>
<a href="https://citation-needed.springer.com/v2/references/{CHAPTER_DOI}?format=bibtex&amp;flavour=citation">.BIB</a>
</body></html>"""


ARTICLE_BIBTEX = (
    "@Article{Lovelace2026,\nauthor=\"Lovelace, Ada\nand Turing, Alan\",\n"
    "title=\"A Verified Springer Article\",\njournal=\"Machine Learning\",\nyear=\"2026\",\n"
    f"month=\"Mar\",\ndoi=\"{ARTICLE_DOI}\"\n}}\n"
).encode("utf-8")
# Springer's chapter exports have no doi field; the DOI is the entry key.
CHAPTER_BIBTEX = (
    f"@InProceedings{{{CHAPTER_DOI},\nauthor=\"Lovelace, Ada\",\n"
    "title=\"Learning Depth from\u00a0Focus\",\nbooktitle=\"Computer Vision -- ECCV 2026\",\n"
    "year=\"2026\",\npublisher=\"Springer Nature Switzerland\",\nisbn=\"978-3-031-00001-1\"\n}\n"
).encode("utf-8")


class Springer:
    """Answers like link.springer.com, including its first-visit cookie handshake."""

    def __init__(self, pages: dict[str, str], *, pdf: bytes = PDF) -> None:
        self.pages = pages
        self.pdf = pdf
        self.requests: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        self.requests.append(f"{url.host}{url.path}")
        if url.host == COOKIE_HOST:
            return httpx.Response(302, headers={
                "Location": url.params["redirect_uri"], "Set-Cookie": "sim=1; Path=/; Domain=springer.com"})
        if url.host == CITATION_HOST:
            doi = url.path.removeprefix("/v2/references/")
            assert url.params["format"] == "bibtex" and url.params["flavour"] == "citation"
            body = ARTICLE_BIBTEX if doi == ARTICLE_DOI else CHAPTER_BIBTEX
            return httpx.Response(200, content=body, headers={"Content-Type": "application/x-bibtex"})
        assert url.host == SPRINGER_HOST
        if url.path.startswith("/content/pdf/"):
            return httpx.Response(200, content=self.pdf, headers={"Content-Type": "application/pdf"})
        if url.path == f"/{ARTICLE_DOI}":
            return httpx.Response(301, headers={"Location": f"/article/{ARTICLE_DOI}"})
        if url.path in self.pages:
            if "sim=1" not in request.headers.get("cookie", ""):
                target = f"https://{SPRINGER_HOST}{url.path}"
                return httpx.Response(303, headers={
                    "Location": f"https://{COOKIE_HOST}/authorize?response_type=cookie&redirect_uri={target}"})
            return httpx.Response(200, text=self.pages[url.path])
        return httpx.Response(404)


def adapter_for(site: Springer) -> SpringerLinkAdapter:
    client = SafeHttpClient(allowed_hosts={SPRINGER_HOST, COOKIE_HOST, CITATION_HOST})
    client._client = httpx.Client(transport=httpx.MockTransport(site), follow_redirects=False)
    return SpringerLinkAdapter(client)


def fetch(tmp_path: Path, adapter, url: str, capsys) -> tuple[int, dict]:
    application = Application.for_test(
        app_root=tmp_path / "app", repository_root=tmp_path / "repository", adapter=adapter)
    code = run_cli(["fetch", "--input", url, "--output", str(tmp_path / "out")],
                   application=application)
    return code, json.loads(capsys.readouterr().out)


def test_article_delivers_the_pdf_and_springer_citation_export(tmp_path, capsys):
    site = Springer({f"/article/{ARTICLE_DOI}": article_page()})

    # The DOI target is the short /10.1007/... form; it redirects to the article page.
    code, payload = fetch(tmp_path, adapter_for(site),
                          f"https://link.springer.com/{ARTICLE_DOI}", capsys)

    assert code == 0, payload
    assert Path(payload["bibtex"]).read_bytes() == ARTICLE_BIBTEX
    record = json.loads(Path(payload["provenance"]).read_text(encoding="utf-8"))
    assert record["bibtex_source"] == "publisher_download"
    assert record["official_landing_url"] == f"https://link.springer.com/article/{ARTICLE_DOI}"
    assert record["official_bibtex_url"] == (
        f"https://citation-needed.springer.com/v2/references/{ARTICLE_DOI}"
        "?format=bibtex&flavour=citation")
    assert record["metadata"]["authors"] == ["Ada Lovelace", "Alan Turing"]
    assert (record["metadata"]["venue"], record["metadata"]["year"]) == ("Machine Learning", 2026)
    assert f"{COOKIE_HOST}/authorize" in site.requests


def test_chapter_uses_the_book_title_as_venue(tmp_path, capsys):
    site = Springer({f"/chapter/{CHAPTER_DOI}": chapter_page()})
    code, payload = fetch(tmp_path, adapter_for(site),
                          f"https://link.springer.com/chapter/{CHAPTER_DOI}", capsys)
    assert code == 0, payload
    record = json.loads(Path(payload["provenance"]).read_text(encoding="utf-8"))
    assert record["metadata"]["venue"] == "Computer Vision – ECCV 2026"
    assert record["metadata"]["publication_type"] == "chapter"


def test_a_page_without_access_is_a_manual_download_and_requests_no_pdf(tmp_path, capsys):
    site = Springer({f"/article/{ARTICLE_DOI}": article_page(has_access="N")})
    code, payload = fetch(tmp_path, adapter_for(site),
                          f"https://link.springer.com/article/{ARTICLE_DOI}", capsys)
    assert (code, payload["error_code"]) == (69, "access_required")
    assert "manual-fetch" in payload["message"]
    assert not any("/content/pdf/" in request for request in site.requests)


def test_an_html_answer_to_the_pdf_request_is_a_manual_download(tmp_path, capsys):
    site = Springer({f"/article/{ARTICLE_DOI}": article_page()}, pdf=b"<html>Log in</html>")
    code, payload = fetch(tmp_path, adapter_for(site),
                          f"https://link.springer.com/article/{ARTICLE_DOI}", capsys)
    assert (code, payload["error_code"]) == (69, "access_required")


def test_other_springer_page_types_have_no_adapter(tmp_path, capsys):
    site = Springer({})
    code, payload = fetch(tmp_path, adapter_for(site),
                          "https://link.springer.com/book/10.1007/978-3-031-00001-1", capsys)
    assert (code, payload["error_code"]) == (69, "unsupported_adapter")
    assert site.requests == []


def test_a_pdf_link_for_another_doi_breaks_the_page_contract():
    site = Springer({f"/article/{ARTICLE_DOI}": article_page(pdf_doi="10.1007/other")})
    with pytest.raises(PageContractChanged, match="PDF URL"):
        adapter_for(site).resolve(f"https://link.springer.com/article/{ARTICLE_DOI}")


def test_a_cloudflare_bot_check_is_reported_as_a_manual_download_with_its_reason():
    from acquire_research_papers.acquisition.adapters.acm import AcmDigitalLibraryAdapter
    from acquire_research_papers.acquisition.base import AccessRequired
    from acquire_research_papers.acquisition.outcomes import failure_outcome
    from acquire_research_papers.http import HttpStatusError

    def challenge(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="Just a moment...", headers={"cf-mitigated": "challenge"})

    client = SafeHttpClient(allowed_hosts={"dl.acm.org"})
    client._client = httpx.Client(transport=httpx.MockTransport(challenge), follow_redirects=False)
    with pytest.raises(HttpStatusError) as raised:
        client.get("https://dl.acm.org/doi/10.1145/1")
    assert raised.value.bot_challenge is True
    outcome = failure_outcome(raised.value)
    assert outcome["error_code"] == "access_required"
    assert "bot check" in outcome["message"] and "manual-fetch" in outcome["message"]

    with pytest.raises(AccessRequired, match="bot check"):
        AcmDigitalLibraryAdapter(client=client).resolve("https://dl.acm.org/doi/10.1145/1")


def test_springer_dois_and_plain_http_links_route_to_springer_link():
    assert doi_publisher_host(ARTICLE_DOI) == SPRINGER_HOST
    assert canonical_landing_url(f"http://link.springer.com/article/{ARTICLE_DOI}") == (
        f"https://link.springer.com/article/{ARTICLE_DOI}")
