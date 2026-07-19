import json
from pathlib import Path

from acquire_research_papers.cli import Application, run_cli
from acquire_research_papers.mineru import MineruCache, MineruResult


VALID_PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"


class FakeMineruRunner:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, pdf: Path, output: Path) -> MineruResult:
        self.calls += 1
        result_dir = output / "precision"
        result_dir.mkdir(parents=True, exist_ok=True)
        markdown = result_dir / "paper.md"
        markdown.write_text("# Parsed paper\n", encoding="utf-8")
        return MineruResult(mode="precision", output_dir=result_dir, markdown=markdown)


def test_export_md_is_explicit_and_reuses_content_cache(tmp_path: Path, capsys) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(VALID_PDF)
    runner = FakeMineruRunner()
    cache = MineruCache(tmp_path / "cache", runner=runner)
    application = Application.for_test(
        app_root=tmp_path / "app",
        repository_root=tmp_path / "repository",
        mineru_cache=cache,
    )

    first_output = tmp_path / "first-md"
    exit_code = run_cli(
        ["export-md", "--pdf", str(pdf), "--output", str(first_output)],
        application=application,
    )
    first = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert first == {
        "markdown": str((first_output / "paper.md").resolve()),
        "mode": "precision",
        "output": str(first_output.resolve()),
        "status": "exported",
    }
    assert runner.calls == 1

    second_output = tmp_path / "second-md"
    exit_code = run_cli(
        ["export-md", "--pdf", str(pdf), "--output", str(second_output)],
        application=application,
    )
    second = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert second["status"] == "exported"
    assert runner.calls == 1
    assert (second_output / "paper.md").read_text(encoding="utf-8") == "# Parsed paper\n"
