import json
from pathlib import Path

import pytest

from acquire_research_papers.acquisition.adapters.open_access import (
    EMBEDDED_BIBTEX_SOURCE,
    AaaiOjsAdapter,
    CvfOpenAccessAdapter,
    IclrProceedingsAdapter,
    NeuripsProceedingsAdapter,
    PmlrAdapter,
    UsenixAdapter,
)
from acquire_research_papers.acquisition.base import PageContractChanged
from acquire_research_papers.acquisition.router import AdapterRouter, canonical_landing_url
from acquire_research_papers.cli import Application, run_cli

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "open_access"
PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"

AAAI_PAGE = "/index.php/AAAI/article/view/27749"
AAAI_PDF = "/index.php/AAAI/article/download/27749/27541"
AAAI_BIBTEX = "/index.php/AAAI/citationstylelanguage/download/bibtex"
AAAI_EXPORT = (
    "@article{Lovelace_Turing_2024, title={A Verified AAAI Paper}, volume={38}, "
    "url={https://ojs.aaai.org/index.php/AAAI/article/view/27749}, "
    "DOI={10.1609/aaai.v38i1.27749}, number={1}, "
    "journal={Proceedings of the AAAI Conference on Artificial Intelligence}, "
    "author={Lovelace, Ada and Turing, Alan}, year={2024}, month={Mar.}, pages={3–11} }"
).encode("utf-8")

NEURIPS_HASH = "0001ca33ba34ce0351e4612b744b3936"
NEURIPS_PAGE = f"/paper_files/paper/2023/hash/{NEURIPS_HASH}-Abstract-Conference.html"
NEURIPS_PDF = f"/paper_files/paper/2023/file/{NEURIPS_HASH}-Paper-Conference.pdf"
NEURIPS_BIBTEX = f"/paper_files/paper/2023/file/{NEURIPS_HASH}-Bibtex.bib"
NEURIPS_EXPORT = (
    "@inproceedings{NEURIPS2023_0001ca33,\n author = {Lovelace, Ada and Turing, Alan},\n"
    " booktitle = {Advances in Neural Information Processing Systems},\n"
    " doi = {10.52202/075280-0001},\n pages = {1--12},\n"
    " publisher = {Curran Associates, Inc.},\n title = {A Verified NeurIPS Paper},\n"
    " volume = {36},\n year = {2023}\n}\n"
).encode("utf-8")

PMLR_PAGE = "/v202/lovelace23a.html"
PMLR_PDF = "/v202/lovelace23a/lovelace23a.pdf"

CVF_PAGE = "/content/CVPR2023/html/Lovelace_A_Verified_CVF_Paper_CVPR_2023_paper.html"
CVF_PDF = "/content/CVPR2023/papers/Lovelace_A_Verified_CVF_Paper_CVPR_2023_paper.pdf"

ICLR_HASH = "00153f90d9177dd3a872133972bc8dea"
ICLR_PAGE = f"/paper_files/paper/2024/hash/{ICLR_HASH}-Abstract-Conference.html"
ICLR_PDF = f"/paper_files/paper/2024/file/{ICLR_HASH}-Paper-Conference.pdf"
ICLR_BIBTEX = f"/paper_files/paper/2024/file/{ICLR_HASH}-Bibtex.bib"
ICLR_EXPORT = (
    "@inproceedings{ICLR2024_00153f90,\n author = {Lovelace, Ada and Turing, Alan},\n"
    " booktitle = {International Conference on Learning Representations},\n"
    " pages = {1--25},\n title = {A Verified ICLR Paper},\n volume = {2024},\n year = {2024}\n}\n"
).encode("utf-8")

USENIX_PAGE = "/conference/osdi24/presentation/lovelace"
USENIX_PDF = "/system/files/osdi24-lovelace.pdf"


def page(name: str, server) -> str:
    origin = server.url("/").rstrip("/")
    return (FIXTURES / f"{name}.html").read_text(encoding="utf-8").replace("{origin}", origin)


def fetch(tmp_path: Path, adapter, url: str, capsys) -> tuple[int, dict]:
    application = Application.for_test(
        app_root=tmp_path / "app", repository_root=tmp_path / "repository", adapter=adapter
    )
    code = run_cli(["fetch", "--input", url, "--output", str(tmp_path / "out")],
                   application=application)
    return code, json.loads(capsys.readouterr().out)


def provenance(payload: dict) -> dict:
    return json.loads(Path(payload["provenance"]).read_text(encoding="utf-8"))


def test_aaai_delivers_the_ojs_bibtex_export(fixture_server, tmp_path, capsys) -> None:
    fixture_server.serve_text(AAAI_PAGE, page("aaai", fixture_server))
    fixture_server.serve_bytes(AAAI_PDF, PDF, "application/pdf")
    fixture_server.serve_bytes(AAAI_BIBTEX, AAAI_EXPORT, "application/x-bibtex")
    adapter = AaaiOjsAdapter(fixture_server.client, production_hosts={fixture_server.host})

    code, payload = fetch(tmp_path, adapter, fixture_server.url(AAAI_PAGE), capsys)

    assert code == 0, payload
    assert Path(payload["bibtex"]).read_bytes() == AAAI_EXPORT
    record = provenance(payload)
    assert record["bibtex_source"] == "publisher_download"
    assert record["official_pdf_url"] == fixture_server.url(AAAI_PDF)
    assert record["official_bibtex_url"].endswith(
        AAAI_BIBTEX + "?submissionId=27749&publicationId=26033")
    assert record["metadata"]["doi"] == "10.1609/aaai.v38i1.27749"
    assert record["metadata"]["authors"] == ["Ada Lovelace", "Alan Turing"]
    assert record["metadata"]["publication_type"] == "AAAI Technical Track on Synthetic Tests"


@pytest.mark.parametrize(("old", "new", "message"), [
    ("submissionId=27749&amp;publicationId=26033\">\n\t\t\t\t<span class=\"fa fa-download\"></span>\n\t\t\t\tBibTeX",
     "submissionId=99999&amp;publicationId=26033\">\n\t\t\t\t<span class=\"fa fa-download\"></span>\n\t\t\t\tBibTeX",
     "BibTeX export"),
    ("article/download/27749/27541", "article/download/99999/27541", "PDF URL"),
    ("10.1609/aaai.v38i1.27749\"/>\n\t<meta name=\"citation_abstract",
     "10.1145/other\"/>\n\t<meta name=\"citation_abstract", "AAAI DOI"),
])
def test_aaai_rejects_a_page_that_disagrees_with_the_article(fixture_server, old, new, message):
    html = page("aaai", fixture_server)
    assert old in html
    fixture_server.serve_text(AAAI_PAGE, html.replace(old, new))
    adapter = AaaiOjsAdapter(fixture_server.client, production_hosts={fixture_server.host})
    with pytest.raises(PageContractChanged, match=message):
        adapter.resolve(fixture_server.url(AAAI_PAGE))


def test_neurips_uses_the_hash_bibtex_file_behind_the_broken_page_link(
    fixture_server, tmp_path, capsys
) -> None:
    fixture_server.serve_text(NEURIPS_PAGE, page("neurips", fixture_server))
    fixture_server.serve_bytes(NEURIPS_PDF, PDF, "application/pdf")
    fixture_server.serve_bytes(NEURIPS_BIBTEX, NEURIPS_EXPORT, "application/x-bibtex")
    adapter = NeuripsProceedingsAdapter(fixture_server.client,
                                        production_hosts={fixture_server.host})

    code, payload = fetch(tmp_path, adapter, fixture_server.url(NEURIPS_PAGE), capsys)

    assert code == 0, payload
    assert Path(payload["bibtex"]).read_bytes() == NEURIPS_EXPORT
    record = provenance(payload)
    assert record["official_bibtex_url"] == fixture_server.url(NEURIPS_BIBTEX)
    assert record["metadata"]["authors"] == ["Ada Lovelace", "Alan Turing"]
    assert record["metadata"]["publication_type"] == "main"


def test_neurips_rejects_pdf_metadata_for_another_paper(fixture_server) -> None:
    html = page("neurips", fixture_server).replace(
        f"{NEURIPS_HASH}-Paper-Conference.pdf\">\n  <meta", "ffff-Paper-Conference.pdf\">\n  <meta")
    fixture_server.serve_text(NEURIPS_PAGE, html)
    adapter = NeuripsProceedingsAdapter(fixture_server.client,
                                        production_hosts={fixture_server.host})
    with pytest.raises(PageContractChanged, match="PDF URL"):
        adapter.resolve(fixture_server.url(NEURIPS_PAGE))


def test_neurips_track_comes_from_the_landing_path(fixture_server) -> None:
    track_page = NEURIPS_PAGE.replace("-Abstract-Conference", "-Abstract-Datasets_and_Benchmarks")
    html = page("neurips", fixture_server).replace("-Paper-Conference.pdf",
                                                    "-Paper-Datasets_and_Benchmarks.pdf")
    fixture_server.serve_text(track_page, html)
    adapter = NeuripsProceedingsAdapter(fixture_server.client,
                                        production_hosts={fixture_server.host})
    document = adapter.resolve(fixture_server.url(track_page))
    assert document.metadata.publication_type == "datasets-and-benchmarks"
    assert document.pdf_url.endswith("-Paper-Datasets_and_Benchmarks.pdf")


def test_pmlr_delivers_the_bibtex_printed_on_the_official_page(
    fixture_server, tmp_path, capsys
) -> None:
    fixture_server.serve_text(PMLR_PAGE, page("pmlr", fixture_server))
    fixture_server.serve_bytes(PMLR_PDF, PDF, "application/pdf")
    adapter = PmlrAdapter(fixture_server.client, production_hosts={fixture_server.host})

    code, payload = fetch(tmp_path, adapter, fixture_server.url(PMLR_PAGE), capsys)

    assert code == 0, payload
    bibtex = Path(payload["bibtex"]).read_text(encoding="utf-8")
    assert bibtex.startswith("@InProceedings{pmlr-v202-lovelace23a,\n  title = \t {Verified Graphs \\& Tests},")
    assert bibtex.endswith("}\n")
    record = provenance(payload)
    assert record["bibtex_source"] == EMBEDDED_BIBTEX_SOURCE
    assert record["official_bibtex_url"] == fixture_server.url(PMLR_PAGE)
    assert record["metadata"]["doi"] is None


def test_pmlr_rejects_a_bibtex_entry_for_another_paper(fixture_server) -> None:
    fixture_server.serve_text(PMLR_PAGE, page("pmlr", fixture_server).replace(
        "pmlr-v202-lovelace23a,", "pmlr-v202-turing23b,"))
    adapter = PmlrAdapter(fixture_server.client, production_hosts={fixture_server.host})
    with pytest.raises(PageContractChanged, match="BibTeX entry"):
        adapter.resolve(fixture_server.url(PMLR_PAGE))


@pytest.mark.parametrize("workshop", [False, True])
def test_cvf_delivers_main_and_workshop_open_access_versions(
    fixture_server, tmp_path, capsys, workshop
) -> None:
    html, landing, pdf = page("cvf", fixture_server), CVF_PAGE, CVF_PDF
    if workshop:
        html = html.replace("/content/CVPR2023/", "/content/CVPR2023W/TCV/").replace(
            "(CVPR)}", "(CVPR) Workshops}")
        landing = landing.replace("/content/CVPR2023/", "/content/CVPR2023W/TCV/")
        pdf = pdf.replace("/content/CVPR2023/", "/content/CVPR2023W/TCV/")
    fixture_server.serve_text(landing, html)
    fixture_server.serve_bytes(pdf, PDF, "application/pdf")
    adapter = CvfOpenAccessAdapter(fixture_server.client, production_hosts={fixture_server.host})

    code, payload = fetch(tmp_path, adapter, fixture_server.url(landing), capsys)

    assert code == 0, payload
    record = provenance(payload)
    assert record["bibtex_source"] == EMBEDDED_BIBTEX_SOURCE
    assert record["metadata"]["publication_type"] == ("workshop" if workshop else "main")
    assert record["metadata"]["publisher"] == "Computer Vision Foundation"
    assert Path(payload["bibtex"]).read_text(encoding="utf-8").startswith(
        "@InProceedings{Lovelace_2023_CVPR,\n    author    = {Lovelace, Ada and Turing, Alan},")


@pytest.mark.parametrize(("old", "new", "message"), [
    ("[<a href=\"/content/CVPR2023/supplemental",
     f"[<a href=\"{CVF_PDF}\">pdf</a>]\n[<a href=\"/content/CVPR2023/supplemental", "one PDF link"),
    ("<div class=\"bibref pre-white-space\">@InProceedings", "<div class=\"bibref\">InProceedings",
     "exactly one BibTeX"),
    ("content=\"2023\"", "content=\"2022\"", "year"),
])
def test_cvf_rejects_ambiguous_or_inconsistent_pages(fixture_server, old, new, message) -> None:
    html = page("cvf", fixture_server)
    assert old in html
    fixture_server.serve_text(CVF_PAGE, html.replace(old, new))
    adapter = CvfOpenAccessAdapter(fixture_server.client, production_hosts={fixture_server.host})
    with pytest.raises(PageContractChanged, match=message):
        adapter.resolve(fixture_server.url(CVF_PAGE))


def test_iclr_delivers_the_proceedings_bibtex_file(fixture_server, tmp_path, capsys) -> None:
    fixture_server.serve_text(ICLR_PAGE, page("iclr", fixture_server))
    fixture_server.serve_bytes(ICLR_PDF, PDF, "application/pdf")
    fixture_server.serve_bytes(ICLR_BIBTEX, ICLR_EXPORT, "application/x-bibtex")
    adapter = IclrProceedingsAdapter(fixture_server.client, production_hosts={fixture_server.host})

    code, payload = fetch(tmp_path, adapter, fixture_server.url(ICLR_PAGE), capsys)

    assert code == 0, payload
    assert Path(payload["bibtex"]).read_bytes() == ICLR_EXPORT
    record = provenance(payload)
    assert record["bibtex_source"] == "publisher_download"
    assert record["metadata"]["publisher"] == "International Conference on Learning Representations"
    assert record["metadata"]["authors"] == ["Ada Lovelace", "Alan Turing"]
    assert record["metadata"]["publication_type"] == "main"


def test_iclr_rejects_a_pdf_for_another_paper(fixture_server) -> None:
    fixture_server.serve_text(ICLR_PAGE, page("iclr", fixture_server).replace(
        f"{ICLR_HASH}-Paper-Conference.pdf\">\n  <meta", "ffff-Paper-Conference.pdf\">\n  <meta"))
    adapter = IclrProceedingsAdapter(fixture_server.client, production_hosts={fixture_server.host})
    with pytest.raises(PageContractChanged, match="ICLR PDF URL"):
        adapter.resolve(fixture_server.url(ICLR_PAGE))


def test_usenix_delivers_the_bibtex_printed_on_the_presentation_page(
    fixture_server, tmp_path, capsys
) -> None:
    fixture_server.serve_text(USENIX_PAGE, page("usenix", fixture_server))
    fixture_server.serve_bytes(USENIX_PDF, PDF, "application/pdf")
    adapter = UsenixAdapter(fixture_server.client, production_hosts={fixture_server.host})

    code, payload = fetch(tmp_path, adapter, fixture_server.url(USENIX_PAGE), capsys)

    assert code == 0, payload
    bibtex = Path(payload["bibtex"]).read_text(encoding="utf-8")
    assert bibtex.startswith("@inproceedings {298669,\n\tauthor = {Ada Lovelace and Alan Turing},")
    assert bibtex.endswith("}\n")
    record = provenance(payload)
    assert record["bibtex_source"] == EMBEDDED_BIBTEX_SOURCE
    assert record["official_pdf_url"] == fixture_server.url(USENIX_PDF)
    # The case-protection braces of the citation title do not reach the metadata title.
    assert record["metadata"]["title"] == "Verified Storage Tiering via Synthetic Tests"
    assert record["metadata"]["publisher"] == "USENIX Association"
    assert record["metadata"]["doi"] is None


@pytest.mark.parametrize(("old", "new", "message"), [
    ("presentation/lovelace},", "presentation/turing},", "different presentation"),
    ('content="2024">', 'content="2023">', "year"),
    ('content="{origin}/system/files/osdi24-lovelace.pdf">',
     'content="{origin}/sites/default/files/osdi24-lovelace.pdf">', "PDF URL"),
])
def test_usenix_rejects_a_page_that_disagrees_with_the_presentation(
    fixture_server, old, new, message
) -> None:
    html = page("usenix", fixture_server)
    origin = fixture_server.url("/").rstrip("/")
    old, new = old.replace("{origin}", origin), new.replace("{origin}", origin)
    assert old in html
    fixture_server.serve_text(USENIX_PAGE, html.replace(old, new))
    adapter = UsenixAdapter(fixture_server.client, production_hosts={fixture_server.host})
    with pytest.raises(PageContractChanged, match=message):
        adapter.resolve(fixture_server.url(USENIX_PAGE))


def test_open_access_archives_are_routed_by_exact_host() -> None:
    router = AdapterRouter.with_defaults()
    assert router.name_for("https://ojs.aaai.org/index.php/AAAI/article/view/1") == "aaai-ojs"
    assert router.name_for("https://proceedings.neurips.cc" + NEURIPS_PAGE) == "neurips-proceedings"
    assert router.name_for("https://proceedings.iclr.cc" + ICLR_PAGE) == "iclr-proceedings"
    assert router.name_for("https://proceedings.mlr.press/v202/x23a.html") == "pmlr"
    assert router.name_for("https://openaccess.thecvf.com" + CVF_PAGE) == "cvf-open-access"
    assert router.name_for("https://www.usenix.org" + USENIX_PAGE) == "usenix"
    assert router.name_for("https://proceedings.mlr.press.evil.example/v202/x23a.html") is None
    assert canonical_landing_url("https://usenix.org" + USENIX_PAGE) == (
        "https://www.usenix.org" + USENIX_PAGE)
    assert canonical_landing_url("http://www.usenix.org" + USENIX_PAGE) == (
        "https://www.usenix.org" + USENIX_PAGE)


def test_known_archive_aliases_are_canonicalized_without_a_request() -> None:
    assert canonical_landing_url(
        f"http://papers.nips.cc/paper/2019/hash/{NEURIPS_HASH}-Abstract.html"
    ) == f"https://proceedings.neurips.cc/paper_files/paper/2019/hash/{NEURIPS_HASH}-Abstract.html"
    assert canonical_landing_url("https://papers.nips.cc" + NEURIPS_PAGE) == (
        "https://proceedings.neurips.cc" + NEURIPS_PAGE)
    assert canonical_landing_url("http://proceedings.mlr.press/v97/abbati19a.html") == (
        "https://proceedings.mlr.press/v97/abbati19a.html")
    assert canonical_landing_url("http://example.org/paper") == "http://example.org/paper"
    # doi.org sends older IEEE DOIs to plain HTTP; the IEEE adapter accepts only HTTPS.
    assert canonical_landing_url("http://ieeexplore.ieee.org/document/7780459/") == (
        "https://ieeexplore.ieee.org/document/7780459/")


def test_source_catalog_lists_open_access_acquisition() -> None:
    from acquire_research_papers.source_catalog import describe_sources

    acquisition = describe_sources()["artifact_acquisition"]
    assert acquisition["AAAI"] == "official_pair"
    assert {"NeurIPS", "PMLR", "CVF"} <= set(acquisition)
