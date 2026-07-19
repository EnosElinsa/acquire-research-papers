import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from acquire_research_papers.mineru import MineruCache, MineruExtractionError, MineruResult


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
        images = result_dir / "images"
        images.mkdir()
        (images / "figure.png").write_bytes(b"png")
        return MineruResult(mode="precision", output_dir=result_dir, markdown=markdown)


def test_research_parse_is_content_addressed(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(VALID_PDF)
    fake = FakeMineruRunner()
    cache = MineruCache(tmp_path / "cache", runner=fake)
    first = cache.parse(pdf)
    second = cache.parse(pdf)
    assert first == second
    assert fake.calls == 1
    assert first.output_dir.parent.name == cache.key_for(pdf)


def test_expired_cache_is_purged_by_last_access(tmp_path: Path) -> None:
    cache = MineruCache(tmp_path / "cache", runner=FakeMineruRunner())
    entry = cache.root / "old-entry"
    output = entry / "precision"
    output.mkdir(parents=True)
    (output / "paper.md").write_text("# Old\n", encoding="utf-8")
    old = datetime.now(UTC) - timedelta(days=8)
    (entry / "metadata.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "key": "old-entry",
                "pdf_sha256": "0" * 64,
                "mode": "precision",
                "output_dir": "precision",
                "markdown": "precision/paper.md",
                "created_at": old.isoformat(),
                "last_accessed": old.isoformat(),
            }
        ),
        encoding="utf-8",
    )
    assert cache.purge_expired(now=datetime.now(UTC)) == ["old-entry"]
    assert not entry.exists()


def test_markdown_is_exported_only_on_explicit_call(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(VALID_PDF)
    cache = MineruCache(tmp_path / "cache", runner=FakeMineruRunner())
    result = cache.parse(pdf)
    destination = tmp_path / "exported-md"
    assert not destination.exists()
    exported = cache.export(result, destination)
    assert exported == destination.resolve()
    assert (exported / "paper.md").is_file()
    assert (exported / "images" / "figure.png").is_file()


def test_existing_parse_lock_is_never_removed_by_another_process(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(VALID_PDF)
    cache = MineruCache(tmp_path / "cache", runner=FakeMineruRunner())
    entry = cache.root / cache.key_for(pdf)
    entry.mkdir(parents=True)
    lock = entry / "parse.lock"
    lock.write_text("other-process", encoding="utf-8")
    with pytest.raises(MineruExtractionError, match="already being parsed"):
        cache.parse(pdf)
    assert lock.read_text(encoding="utf-8") == "other-process"
