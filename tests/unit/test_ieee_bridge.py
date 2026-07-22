from pathlib import Path

import pytest

from acquire_research_papers.acquisition.adapters.ieee import (
    IeeeBridge,
    IeeeBridgeResult,
    IeeeXploreAdapter,
)
from acquire_research_papers.bibliography import BibMissing
from acquire_research_papers.cli import build_parser


def bridge_result(*, bibtex: str | None = None) -> IeeeBridgeResult:
    return IeeeBridgeResult(
        title="A Synthetic IEEE Paper",
        authors=("Ada Lovelace", "Alan Turing"),
        year=2026,
        venue="IEEE Transactions on Testing",
        doi="10.1109/test.1",
        landing_url="https://ieeexplore.ieee.org/document/1",
        pdf_url="https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?arnumber=1",
        bibtex_url="https://ieeexplore.ieee.org/xpl/downloadCitations",
        pdf_bytes=b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n",
        bibtex=(
            bibtex
            if bibtex is not None
            else "@article{k,title={A Synthetic IEEE Paper},"
            "author={Lovelace, Ada and Turing, Alan},year={2026},"
            "journal={IEEE Transactions on Testing},doi={10.1109/test.1}}"
        ),
    )


def test_ieee_bridge_uses_dedicated_runtime_paths(tmp_path: Path) -> None:
    bridge = IeeeBridge(
        script=tmp_path / "ieee-playwright.mjs",
        profile_root=tmp_path / "profiles" / "ieee",
        dependency_root=tmp_path / "deps",
        work_root=tmp_path / "runs",
        secret_path=tmp_path / "secrets" / "secrets.clixml",
        node_path="node",
    )
    command = bridge.command(
        "https://ieeexplore.ieee.org/document/11014597",
        run_dir=tmp_path / "runs" / "run-1",
    )
    rendered = " ".join(str(value) for value in command)
    assert "Google\\Chrome\\User Data" not in rendered
    assert str(tmp_path / "profiles" / "ieee") in command
    assert str(tmp_path / "deps") in command
    assert "--secret-path" in command
    assert command[-2:] == ["--accept-attribute-release", "true"]

    manual_bridge = IeeeBridge(
        script=tmp_path / "ieee-playwright.mjs",
        profile_root=tmp_path / "profiles" / "ieee",
        dependency_root=tmp_path / "deps",
        work_root=tmp_path / "runs",
        secret_path=tmp_path / "secrets" / "secrets.clixml",
        node_path="node",
        accept_attribute_release=False,
    )
    manual_command = manual_bridge.command(
        "https://ieeexplore.ieee.org/document/11014597",
        run_dir=tmp_path / "runs" / "run-2",
    )
    assert manual_command[-2:] == ["--accept-attribute-release", "false"]


def test_ieee_attribute_release_is_automatic_with_an_explicit_opt_out(tmp_path: Path) -> None:
    parser = build_parser()
    ordinary = parser.parse_args(
        ["fetch", "--input", "10.1109/test.1", "--output", str(tmp_path / "ordinary")]
    )
    manual = parser.parse_args(
        [
            "fetch",
            "--input", "10.1109/test.1",
            "--output", str(tmp_path / "manual"),
            "--no-accept-ieee-attribute-release",
        ]
    )
    assert ordinary.accept_ieee_attribute_release is True
    assert manual.accept_ieee_attribute_release is False


class StubBridge:
    def __init__(self, result: IeeeBridgeResult) -> None:
        self.result = result
        self.calls: list[str] = []

    def retrieve(self, reference: str) -> IeeeBridgeResult:
        self.calls.append(reference)
        return self.result


def test_ieee_adapter_returns_one_cached_official_pair() -> None:
    bridge = StubBridge(bridge_result())
    adapter = IeeeXploreAdapter(bridge)
    document = adapter.resolve("https://ieeexplore.ieee.org/document/1")
    pair = adapter.acquire(document)
    assert pair.document.metadata.title == "A Synthetic IEEE Paper"
    assert pair.bibtex_text.startswith("@article")
    assert bridge.calls == ["https://ieeexplore.ieee.org/document/1"]


def test_ieee_adapter_requires_official_bibtex() -> None:
    bridge = StubBridge(bridge_result(bibtex=""))
    with pytest.raises(BibMissing):
        IeeeXploreAdapter(bridge).resolve("https://ieeexplore.ieee.org/document/1")


def test_ieee_adapter_rejects_lookalike_hostname() -> None:
    adapter = IeeeXploreAdapter(StubBridge(bridge_result()))
    assert adapter.supports("https://ieeexplore.ieee.org/document/1")
    assert not adapter.supports("https://ieeexplore.ieee.org.evil.example/document/1")
