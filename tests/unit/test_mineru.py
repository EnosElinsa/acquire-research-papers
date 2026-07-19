from pathlib import Path
from subprocess import CompletedProcess

import pytest

from acquire_research_papers.mineru import (
    MineruCliRunner,
    MineruExtractionError,
    MineruRateLimited,
)


VALID_PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"


def write_pdf(path: Path) -> None:
    path.write_bytes(VALID_PDF)


def test_precision_cli_receives_token_only_in_child_environment(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    write_pdf(pdf)
    calls = []

    def process_runner(command, **kwargs):
        calls.append((command, kwargs))
        output = Path(command[command.index("-o") + 1])
        output.mkdir(parents=True, exist_ok=True)
        (output / "paper.md").write_text("# Parsed\n", encoding="utf-8")
        return CompletedProcess(command, 0, stdout="ok", stderr="")

    runner = MineruCliRunner(
        token_provider=lambda: "synthetic-token",
        process_runner=process_runner,
        executable="mineru-open-api",
    )
    result = runner(pdf, tmp_path / "cache")
    command, kwargs = calls[0]
    assert command[:3] == ["mineru-open-api", "extract", str(pdf)]
    assert kwargs["env"]["MINERU_TOKEN"] == "synthetic-token"
    assert "synthetic-token" not in " ".join(command)
    assert result.mode == "precision"
    assert result.markdown.name == "paper.md"


def test_exact_cdn_eof_failure_uses_one_token_free_flash_fallback(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    write_pdf(pdf)
    calls = []

    def process_runner(command, **kwargs):
        calls.append((command, kwargs))
        if command[1] == "extract":
            return CompletedProcess(
                command,
                1,
                stdout="Downloading result ZIP archive",
                stderr="https://cdn-mineru.openxlab.org.cn/result.zip unexpected EOF during TLS",
            )
        output = Path(command[command.index("-o") + 1])
        output.mkdir(parents=True, exist_ok=True)
        (output / "paper.md").write_text("# Flash\n", encoding="utf-8")
        return CompletedProcess(command, 0, stdout="ok", stderr="")

    runner = MineruCliRunner(
        token_provider=lambda: "synthetic-token",
        process_runner=process_runner,
        executable="mineru-open-api",
    )
    result = runner(pdf, tmp_path / "cache")
    assert [call[0][1] for call in calls] == ["extract", "flash-extract"]
    assert "MINERU_TOKEN" not in calls[1][1]["env"]
    assert result.mode == "flash-extract"


def test_other_precision_failure_does_not_trigger_flash(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    write_pdf(pdf)
    calls = 0

    def process_runner(command, **kwargs):
        nonlocal calls
        calls += 1
        return CompletedProcess(command, 1, stdout="", stderr="generic server failure")

    runner = MineruCliRunner(
        token_provider=lambda: "synthetic-token",
        process_runner=process_runner,
        executable="mineru-open-api",
    )
    with pytest.raises(MineruExtractionError):
        runner(pdf, tmp_path / "cache")
    assert calls == 1


def test_token_is_redacted_from_failures(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    write_pdf(pdf)

    def process_runner(command, **kwargs):
        return CompletedProcess(command, 1, stdout="", stderr="failed synthetic-token")

    runner = MineruCliRunner(
        token_provider=lambda: "synthetic-token",
        process_runner=process_runner,
        executable="mineru-open-api",
    )
    with pytest.raises(MineruExtractionError) as captured:
        runner(pdf, tmp_path / "cache")
    assert "synthetic-token" not in str(captured.value)


def test_rate_limit_is_classified_without_fallback(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    write_pdf(pdf)

    def process_runner(command, **kwargs):
        return CompletedProcess(command, 1, stdout="", stderr="HTTP 429 too many requests")

    runner = MineruCliRunner(
        token_provider=lambda: "synthetic-token",
        process_runner=process_runner,
        executable="mineru-open-api",
    )
    with pytest.raises(MineruRateLimited):
        runner(pdf, tmp_path / "cache")
