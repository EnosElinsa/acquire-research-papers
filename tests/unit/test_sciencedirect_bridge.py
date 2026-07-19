from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from acquire_research_papers.acquisition.adapters.sciencedirect_bridge import (
    ScienceDirectBridge,
    ScienceDirectBridgeError,
)


def test_sciencedirect_bridge_uses_dedicated_runtime_paths(tmp_path: Path) -> None:
    bridge = ScienceDirectBridge(
        script=tmp_path / "sciencedirect-playwright.mjs",
        profile_root=tmp_path / "profiles" / "sciencedirect-scau",
        dependency_root=tmp_path / "deps",
        work_root=tmp_path / "runs",
        secret_path=tmp_path / "secrets" / "secrets.clixml",
        node_path="node",
    )
    command = bridge.command(
        "https://www.sciencedirect.com/science/article/pii/S1049007824000411",
        run_dir=tmp_path / "runs" / "run-1",
    )
    assert "Google\\Chrome\\User Data" not in " ".join(command)
    assert str(tmp_path / "profiles" / "sciencedirect-scau") in command
    assert str(tmp_path / "deps") in command
    assert "--secret-path" in command


def test_sciencedirect_bridge_rejects_pdf_outside_its_run_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = ScienceDirectBridge(
        script=tmp_path / "sciencedirect-playwright.mjs",
        profile_root=tmp_path / "profiles" / "sciencedirect-scau",
        dependency_root=tmp_path / "deps",
        work_root=tmp_path / "runs",
        secret_path=tmp_path / "secrets" / "secrets.clixml",
        node_path="node",
    )
    outside_pdf = tmp_path / "outside.pdf"
    outside_pdf.write_bytes(b"%PDF-1.7\n%%EOF\n")
    payload = {
        "status": "downloaded",
        "pdfPath": str(outside_pdf),
    }
    monkeypatch.setattr(bridge, "_ensure_dependency", lambda: None)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        ),
    )
    with pytest.raises(ScienceDirectBridgeError) as caught:
        bridge.retrieve("https://www.sciencedirect.com/science/article/pii/S1049007824000411")
    assert caught.value.phase == "path-boundary"


def test_sciencedirect_bridge_preserves_structured_failure_phase(tmp_path: Path) -> None:
    bridge = ScienceDirectBridge(
        script=tmp_path / "sciencedirect-playwright.mjs",
        profile_root=tmp_path / "profiles" / "sciencedirect-scau",
        dependency_root=tmp_path / "deps",
        work_root=tmp_path / "runs",
        secret_path=tmp_path / "secrets" / "secrets.clixml",
    )
    error = bridge._failure(
        '{"status":"error","phase":"atrust-required",'
        '"message":"SCAU WebVPN did not expose the subscribed Elsevier PDF."}'
    )
    assert error.phase == "atrust-required"
    assert "WebVPN" in str(error)
