from __future__ import annotations

import json
from pathlib import Path

import pytest

from acquire_research_papers.acquisition.adapters.elsevier_api import ElsevierSearchRecord
from acquire_research_papers.acquisition.base import SourceDocument
from acquire_research_papers.acquisition import manual_handoff
from acquire_research_papers.acquisition.manual_handoff import ManualDownloadWatcher
from acquire_research_papers.acquisition.manual_handoff import ManualSourceChanged
from acquire_research_papers.cli import Application, run_cli
from acquire_research_papers.models import PaperMetadata, PaperStatus


def _pdf_with_text(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    content = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(content))
        content.extend(f"{number} 0 obj\n".encode())
        content.extend(body + b"\nendobj\n")
    xref = len(content)
    content.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        content.extend(f"{offset:010d} 00000 n \n".encode())
    content.extend(
        f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(content)


def _record() -> ElsevierSearchRecord:
    metadata = PaperMetadata(
        title="Manual Verified Paper",
        authors=("Lovelace",),
        authors_complete=False,
        year=2026,
        venue="Journal of Manual Acquisition",
        doi="10.1016/j.manual.2026.1",
        publisher="Elsevier ScienceDirect",
        landing_url="https://www.sciencedirect.com/science/article/pii/S0123456789000001",
    )
    document = SourceDocument(
        metadata=metadata,
        pdf_url=metadata.landing_url + "/pdfft",
        bibtex_url=(
            "https://www.sciencedirect.com/sdfe/arp/cite?"
            "pii=S0123456789000001&format=text/x-bibtex&withabstract=true"
        ),
        allowed_hosts=frozenset({"www.sciencedirect.com"}),
    )
    return ElsevierSearchRecord(
        pii="S0123456789000001",
        document=document,
        metadata_url=(
            "https://api.elsevier.com/content/search/scopus?"
            "query=PII%28S0123456789000001%29"
        ),
    )


def _write_downloads(root: Path) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    pdf = root / "download.pdf"
    bib = root / "download.bib"
    pdf.write_bytes(_pdf_with_text("Manual Verified Paper DOI 10.1016/j.manual.2026.1"))
    bib.write_text(
        "@article{manual,title={Manual Verified Paper},"
        "author={Lovelace, Ada and Turing, Alan},year={2026},"
        "journal={Journal of Manual Acquisition},doi={10.1016/j.manual.2026.1}}",
        encoding="utf-8",
    )
    return pdf, bib


class StubResolver:
    def __init__(self) -> None:
        self.calls = 0

    def resolve(self, reference: str) -> ElsevierSearchRecord:
        self.calls += 1
        assert reference in {
            "10.1016/j.manual.2026.1",
            "https://www.sciencedirect.com/science/article/pii/S0123456789000001",
        }
        return _record()


def _workflow(**kwargs):
    assert hasattr(manual_handoff, "ManualHandoffWorkflow"), "workflow is not implemented"
    return manual_handoff.ManualHandoffWorkflow(**kwargs)


def _application(tmp_path: Path, workflow) -> Application:
    return Application.for_test(
        app_root=tmp_path / "app",
        repository_root=tmp_path / "repository",
        manual_handoff=workflow,
    )


def test_manual_fetch_direct_paths_deliver_and_preserve_sources(tmp_path, capsys) -> None:
    downloads = tmp_path / "downloads"
    source_pdf, source_bib = _write_downloads(downloads)
    original_pdf = source_pdf.read_bytes()
    original_bib = source_bib.read_bytes()
    opened: list[str] = []
    resolver = StubResolver()
    app = _application(
        tmp_path,
        _workflow(resolver=resolver, opener=lambda url: opened.append(url) or True),
    )

    exit_code = run_cli(
        [
            "manual-fetch",
            "--input",
            "10.1016/j.manual.2026.1",
            "--pdf",
            str(source_pdf),
            "--bibtex",
            str(source_bib),
            "--output",
            str(tmp_path / "out"),
        ],
        application=app,
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert captured.out.count("\n") == 1
    assert captured.err == ""
    assert payload["status"] == "delivered"
    assert opened == []
    assert source_pdf.read_bytes() == original_pdf
    assert source_bib.read_bytes() == original_bib
    provenance = json.loads(Path(payload["provenance"]).read_text(encoding="utf-8"))
    assert provenance["acquisition_method"] == "manual_publisher_download"
    assert provenance["metadata_author_scope"] == "first_author"
    assert provenance["source_pdf_filename"] == "download.pdf"
    assert provenance["source_bibtex_filename"] == "download.bib"
    assert app.registry.status(provenance["paper_id"]) is PaperStatus.DELIVERED


def test_manual_fetch_watch_opens_only_canonical_page_then_takes_over(tmp_path, capsys) -> None:
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    opened: list[str] = []

    def opener(url: str) -> bool:
        opened.append(url)
        _write_downloads(downloads)
        return True

    workflow = _workflow(
        resolver=StubResolver(),
        opener=opener,
        watcher_factory=lambda root: ManualDownloadWatcher(root, poll_interval=0.001),
    )
    app = _application(tmp_path, workflow)

    exit_code = run_cli(
        [
            "manual-fetch",
            "--input",
            "https://www.sciencedirect.com/science/article/pii/S0123456789000001",
            "--watch",
            str(downloads),
            "--timeout",
            "2",
            "--output",
            str(tmp_path / "out"),
        ],
        application=app,
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(captured.out)["status"] == "delivered"
    assert opened == [_record().document.metadata.landing_url]
    assert "Download the official PDF and raw BibTeX" in captured.err
    assert str(downloads.resolve()) in captured.err


def test_manual_fetch_requires_both_explicit_paths(tmp_path, capsys) -> None:
    downloads = tmp_path / "downloads"
    pdf, _ = _write_downloads(downloads)
    resolver = StubResolver()
    app = _application(tmp_path, _workflow(resolver=resolver, opener=lambda url: True))

    exit_code = run_cli(
        [
            "manual-fetch",
            "--input",
            "10.1016/j.manual.2026.1",
            "--pdf",
            str(pdf),
            "--output",
            str(tmp_path / "out"),
        ],
        application=app,
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 64
    assert payload["error_code"] == "invalid_input"
    assert resolver.calls == 0


def test_manual_fetch_rejects_nonpositive_timeout_before_metadata_request(tmp_path, capsys) -> None:
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    resolver = StubResolver()
    app = _application(tmp_path, _workflow(resolver=resolver, opener=lambda url: True))

    exit_code = run_cli(
        [
            "manual-fetch",
            "--input",
            "10.1016/j.manual.2026.1",
            "--watch",
            str(downloads),
            "--timeout",
            "0",
            "--output",
            str(tmp_path / "out"),
        ],
        application=app,
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 64
    assert payload["error_code"] == "invalid_input"
    assert resolver.calls == 0


@pytest.mark.parametrize("timeout", ["nan", "inf", "-inf"])
def test_manual_fetch_rejects_nonfinite_timeout_before_metadata_request(
    tmp_path,
    capsys,
    timeout: str,
) -> None:
    pdf, bib = _write_downloads(tmp_path / "downloads")
    resolver = StubResolver()
    app = _application(tmp_path, _workflow(resolver=resolver, opener=lambda url: True))

    exit_code = run_cli(
        [
            "manual-fetch",
            "--input",
            "10.1016/j.manual.2026.1",
            "--pdf",
            str(pdf),
            "--bibtex",
            str(bib),
            f"--timeout={timeout}",
            "--output",
            str(tmp_path / "out"),
        ],
        application=app,
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 64
    assert payload["error_code"] == "invalid_input"
    assert resolver.calls == 0


def test_manual_fetch_rejects_missing_explicit_files_before_metadata_request(
    tmp_path,
    capsys,
) -> None:
    resolver = StubResolver()
    app = _application(tmp_path, _workflow(resolver=resolver, opener=lambda url: True))

    exit_code = run_cli(
        [
            "manual-fetch",
            "--input",
            "10.1016/j.manual.2026.1",
            "--pdf",
            str(tmp_path / "missing.pdf"),
            "--bibtex",
            str(tmp_path / "missing.bib"),
            "--output",
            str(tmp_path / "out"),
        ],
        application=app,
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 64
    assert payload["error_code"] == "invalid_input"
    assert resolver.calls == 0


def test_manual_fetch_reuses_verified_delivery_without_resolving_again(tmp_path, capsys) -> None:
    pdf, bib = _write_downloads(tmp_path / "downloads")
    resolver = StubResolver()
    app = _application(tmp_path, _workflow(resolver=resolver, opener=lambda url: True))
    argv = [
        "manual-fetch",
        "--input",
        "10.1016/j.manual.2026.1",
        "--pdf",
        str(pdf),
        "--bibtex",
        str(bib),
        "--output",
        str(tmp_path / "out"),
    ]

    assert run_cli(argv, application=app) == 0
    first = json.loads(capsys.readouterr().out)
    assert run_cli(argv, application=app) == 0
    second = json.loads(capsys.readouterr().out)

    assert second == first
    assert resolver.calls == 1


def test_manual_fetch_classifies_a_source_change_as_contract_error(tmp_path, capsys) -> None:
    pdf, bib = _write_downloads(tmp_path / "downloads")

    class ChangedWorkflow:
        def acquire(self, *args, **kwargs):
            raise ManualSourceChanged("manual source changed")

    app = _application(tmp_path, ChangedWorkflow())

    exit_code = run_cli(
        [
            "manual-fetch",
            "--input",
            "10.1016/j.manual.2026.1",
            "--pdf",
            str(pdf),
            "--bibtex",
            str(bib),
            "--output",
            str(tmp_path / "out"),
        ],
        application=app,
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 78
    assert payload["error_code"] == "contract_error"


def test_manual_fetch_classifies_non_utf8_bibtex_as_contract_error(tmp_path, capsys) -> None:
    pdf, bib = _write_downloads(tmp_path / "downloads")
    bib.write_bytes(b"\xff\xfe\x00")
    app = _application(
        tmp_path,
        _workflow(resolver=StubResolver(), opener=lambda url: True),
    )

    exit_code = run_cli(
        [
            "manual-fetch",
            "--input",
            "10.1016/j.manual.2026.1",
            "--pdf",
            str(pdf),
            "--bibtex",
            str(bib),
            "--output",
            str(tmp_path / "out"),
        ],
        application=app,
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 78
    assert payload["error_code"] == "contract_error"


def test_manual_fetch_rejects_output_inside_the_skill_repository(tmp_path, capsys) -> None:
    pdf, bib = _write_downloads(tmp_path / "downloads")
    resolver = StubResolver()
    app = _application(tmp_path, _workflow(resolver=resolver, opener=lambda url: True))

    exit_code = run_cli(
        [
            "manual-fetch",
            "--input",
            "10.1016/j.manual.2026.1",
            "--pdf",
            str(pdf),
            "--bibtex",
            str(bib),
            "--output",
            str(tmp_path / "repository" / "out"),
        ],
        application=app,
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 64
    assert payload["error_code"] == "invalid_input"
    assert resolver.calls == 0


def test_manual_fetch_classifies_browser_launch_failure(tmp_path, capsys) -> None:
    downloads = tmp_path / "downloads"
    downloads.mkdir()

    def failing_opener(url: str) -> bool:
        raise OSError("no browser is registered")

    app = _application(
        tmp_path,
        _workflow(resolver=StubResolver(), opener=failing_opener),
    )

    exit_code = run_cli(
        [
            "manual-fetch",
            "--input",
            "10.1016/j.manual.2026.1",
            "--watch",
            str(downloads),
            "--timeout",
            "1",
            "--output",
            str(tmp_path / "out"),
        ],
        application=app,
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 69
    assert payload["error_code"] == "manual_handoff_required"
    assert "no browser" not in captured.out
