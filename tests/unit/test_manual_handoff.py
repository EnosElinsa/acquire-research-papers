from __future__ import annotations

from pathlib import Path

import pytest

from acquire_research_papers.acquisition.base import SourceDocument
from acquire_research_papers.models import PaperMetadata

try:
    from acquire_research_papers.acquisition import manual_handoff
except ImportError:
    manual_handoff = None


def _module():
    assert manual_handoff is not None, "manual_handoff module is not implemented"
    return manual_handoff


def _pdf_with_text(text: str) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    content = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(content))
        content.extend(f"{number} 0 obj\n".encode("ascii"))
        content.extend(body)
        content.extend(b"\nendobj\n")
    xref = len(content)
    content.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    content.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        content.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    content.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(content)


def _document() -> SourceDocument:
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
    return SourceDocument(
        metadata=metadata,
        pdf_url=metadata.landing_url + "/pdfft",
        bibtex_url=(
            "https://www.sciencedirect.com/sdfe/arp/cite?"
            "pii=S0123456789000001&format=text/x-bibtex&withabstract=true"
        ),
        allowed_hosts=frozenset({"www.sciencedirect.com"}),
    )


def _bibtex(*, first_author: str = "Lovelace", title: str = "Manual Verified Paper") -> str:
    return (
        f"@article{{manual,title={{{title}}},"
        f"author={{{first_author}, Ada and Turing, Alan}},year={{2026}},"
        "journal={Journal of Manual Acquisition},doi={10.1016/j.manual.2026.1}}"
    )


def _write_pair(
    root: Path,
    stem: str,
    *,
    pdf_text: str = "Manual Verified Paper DOI 10.1016/j.manual.2026.1",
    bibtex: str | None = None,
    pdf_suffix: bytes = b"",
) -> tuple[Path, Path]:
    pdf = root / f"{stem}.pdf"
    bib = root / f"{stem}.bib"
    pdf.write_bytes(_pdf_with_text(pdf_text) + pdf_suffix)
    bib.write_text(bibtex or _bibtex(), encoding="utf-8")
    return pdf, bib


class FakeTime:
    def __init__(self, on_sleep=None) -> None:
        self.now = 0.0
        self.sleep_calls = 0
        self.on_sleep = on_sleep

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleep_calls += 1
        self.now += seconds
        if self.on_sleep is not None:
            self.on_sleep(self.sleep_calls)


def _watcher(root: Path, fake_time: FakeTime):
    module = _module()
    assert hasattr(module, "ManualDownloadWatcher"), "watcher is not implemented"
    return module.ManualDownloadWatcher(
        root,
        poll_interval=1.0,
        stable_polls=2,
        monotonic=fake_time.monotonic,
        sleeper=fake_time.sleep,
    )


def test_direct_pair_validates_pdf_and_raw_bibtex(tmp_path: Path) -> None:
    pdf, bib = _write_pair(tmp_path, "download")
    module = _module()
    assert hasattr(module, "validate_manual_pair"), "pair validator is not implemented"

    selected = module.validate_manual_pair(_document(), pdf, bib)

    assert selected.source_pdf == pdf.resolve()
    assert selected.source_bibtex == bib.resolve()
    assert selected.pair.pdf_bytes == pdf.read_bytes()
    assert selected.pair.bibtex_text == _bibtex()


def test_direct_pair_preserves_utf8_bom_and_crlf_bibtex_bytes(tmp_path: Path) -> None:
    pdf, bib = _write_pair(tmp_path, "raw-bytes")
    raw = ("\ufeff" + _bibtex().replace(",", ",\r\n")).encode("utf-8")
    bib.write_bytes(raw)
    module = _module()

    selected = module.validate_manual_pair(_document(), pdf, bib)

    assert selected.pair.bibtex_text.encode("utf-8") == raw


def test_direct_pair_rejects_pdf_for_a_different_work(tmp_path: Path) -> None:
    pdf, bib = _write_pair(tmp_path, "wrong", pdf_text="A different article DOI 10.1000/wrong")
    module = _module()
    assert hasattr(module, "validate_manual_pair"), "pair validator is not implemented"

    with pytest.raises(module.PdfIdentityMismatch):
        module.validate_manual_pair(_document(), pdf, bib)

    assert pdf.is_file()
    assert bib.is_file()


@pytest.mark.parametrize(
    "pdf_text",
    [
        "A Different Paper cites DOI 10.1016/j.manual.2026.1",
        "Manual Verified Paper but DOI 10.1000/a-different-work",
    ],
)
def test_pdf_identity_requires_both_target_title_and_doi(
    tmp_path: Path,
    pdf_text: str,
) -> None:
    pdf, bib = _write_pair(tmp_path, "partial-identity", pdf_text=pdf_text)
    module = _module()

    with pytest.raises(module.PdfIdentityMismatch):
        module.validate_manual_pair(_document(), pdf, bib)


def test_direct_pair_rejects_source_changed_after_identity_validation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pdf, bib = _write_pair(tmp_path, "changing")
    module = _module()
    assert hasattr(module, "ManualSourceChanged"), "source-change error is not implemented"
    real_validator = module.validate_pdf_identity

    def validate_then_replace(path: Path, document: SourceDocument) -> None:
        real_validator(path, document)
        path.write_bytes(_pdf_with_text("Different paper DOI 10.1000/changed"))

    monkeypatch.setattr(module, "validate_pdf_identity", validate_then_replace)

    with pytest.raises(module.ManualSourceChanged):
        module.validate_manual_pair(_document(), pdf, bib)


def test_watcher_ignores_baseline_files_and_selects_only_new_pair(tmp_path: Path) -> None:
    _write_pair(tmp_path, "old")
    fake_time = FakeTime()
    watcher = _watcher(tmp_path, fake_time)
    baseline = watcher.snapshot()
    expected_pdf, expected_bib = _write_pair(tmp_path, "new")

    selected = watcher.wait_for_pair(_document(), baseline, timeout_seconds=5)

    assert selected.source_pdf == expected_pdf.resolve()
    assert selected.source_bibtex == expected_bib.resolve()
    assert fake_time.sleep_calls == 1


def test_watcher_accepts_an_existing_filename_modified_after_snapshot(tmp_path: Path) -> None:
    pdf = tmp_path / "article.pdf"
    bib = tmp_path / "article.bib"
    pdf.write_bytes(b"placeholder")
    bib.write_text("placeholder", encoding="utf-8")
    fake_time = FakeTime()
    watcher = _watcher(tmp_path, fake_time)
    baseline = watcher.snapshot()
    pdf.write_bytes(_pdf_with_text("Manual Verified Paper DOI 10.1016/j.manual.2026.1"))
    bib.write_text(_bibtex(), encoding="utf-8")

    selected = watcher.wait_for_pair(_document(), baseline, timeout_seconds=5)

    assert selected.source_pdf == pdf.resolve()
    assert selected.source_bibtex == bib.resolve()


def test_watcher_waits_for_two_unchanged_polls_and_ignores_partials(tmp_path: Path) -> None:
    pdf, bib = _write_pair(tmp_path, "download")
    partial = tmp_path / "unrelated.pdf.crdownload"
    partial.write_bytes(_pdf_with_text("Manual Verified Paper DOI 10.1016/j.manual.2026.1"))

    def mutate_first_poll(sleep_calls: int) -> None:
        if sleep_calls == 1:
            pdf.write_bytes(
                _pdf_with_text("Manual Verified Paper DOI 10.1016/j.manual.2026.1 finalized")
            )

    fake_time = FakeTime(on_sleep=mutate_first_poll)
    watcher = _watcher(tmp_path, fake_time)
    baseline = watcher.snapshot()
    # Make both valid candidates post-snapshot while preserving the partial as ineligible.
    pdf.write_bytes(_pdf_with_text("Manual Verified Paper DOI 10.1016/j.manual.2026.1 writing"))
    bib.write_text(_bibtex() + "\n", encoding="utf-8")

    selected = watcher.wait_for_pair(_document(), baseline, timeout_seconds=6)

    assert selected.source_pdf == pdf.resolve()
    assert fake_time.sleep_calls >= 2


def test_watcher_deduplicates_identical_valid_downloads_by_hash(tmp_path: Path) -> None:
    fake_time = FakeTime()
    watcher = _watcher(tmp_path, fake_time)
    baseline = watcher.snapshot()
    first_pdf, first_bib = _write_pair(tmp_path, "first")
    (tmp_path / "second.pdf").write_bytes(first_pdf.read_bytes())
    (tmp_path / "second.bib").write_bytes(first_bib.read_bytes())

    selected = watcher.wait_for_pair(_document(), baseline, timeout_seconds=5)

    assert selected.pair.pdf_bytes == first_pdf.read_bytes()
    assert selected.pair.bibtex_text == first_bib.read_text(encoding="utf-8")


def test_watcher_rejects_multiple_distinct_valid_pdfs(tmp_path: Path) -> None:
    module = _module()
    fake_time = FakeTime()
    watcher = _watcher(tmp_path, fake_time)
    baseline = watcher.snapshot()
    _write_pair(tmp_path, "first")
    (tmp_path / "second.pdf").write_bytes(
        _pdf_with_text("Manual Verified Paper DOI 10.1016/j.manual.2026.1 second copy")
    )

    with pytest.raises(module.ManualDownloadAmbiguous):
        watcher.wait_for_pair(_document(), baseline, timeout_seconds=5)


def test_watcher_times_out_when_only_unrelated_stable_files_exist(tmp_path: Path) -> None:
    module = _module()
    fake_time = FakeTime()
    watcher = _watcher(tmp_path, fake_time)
    baseline = watcher.snapshot()
    _write_pair(
        tmp_path,
        "wrong",
        pdf_text="Unrelated PDF DOI 10.1000/wrong",
        bibtex=_bibtex(first_author="Turing", title="Unrelated Paper"),
    )

    with pytest.raises(module.ManualDownloadTimeout, match="stable PDF=1.*BibTeX=1"):
        watcher.wait_for_pair(_document(), baseline, timeout_seconds=3)


def test_watcher_does_not_reparse_an_unchanged_invalid_pdf(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _module()
    fake_time = FakeTime()
    watcher = _watcher(tmp_path, fake_time)
    baseline = watcher.snapshot()
    (tmp_path / "wrong.pdf").write_bytes(_pdf_with_text("Different paper DOI 10.1000/wrong"))
    calls = 0
    real_validator = module.validate_pdf_identity

    def counting_validator(path: Path, document: SourceDocument) -> None:
        nonlocal calls
        calls += 1
        real_validator(path, document)

    monkeypatch.setattr(module, "validate_pdf_identity", counting_validator)

    with pytest.raises(module.ManualDownloadTimeout):
        watcher.wait_for_pair(_document(), baseline, timeout_seconds=4)

    assert calls == 1


def test_watcher_restarts_stability_after_source_changes_during_final_read(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _module()
    fake_time = FakeTime()
    watcher = _watcher(tmp_path, fake_time)
    baseline = watcher.snapshot()
    expected_pdf, expected_bib = _write_pair(tmp_path, "changing-final-read")
    calls = 0
    real_validator = module.validate_manual_pair

    def changed_once(document, pdf, bibtex):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise module.ManualSourceChanged("source still moving")
        return real_validator(document, pdf, bibtex)

    monkeypatch.setattr(module, "validate_manual_pair", changed_once)

    selected = watcher.wait_for_pair(_document(), baseline, timeout_seconds=6)

    assert selected.source_pdf == expected_pdf.resolve()
    assert selected.source_bibtex == expected_bib.resolve()
    assert calls == 2
