import json
import subprocess
import sys
import time
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


def test_changed_markdown_is_not_reused_as_verified_cache(tmp_path: Path) -> None:
    pdf = tmp_path / 'paper.pdf'
    pdf.write_bytes(VALID_PDF)
    fake = FakeMineruRunner()
    cache = MineruCache(tmp_path / 'cache', runner=fake)
    parsed = cache.parse(pdf)
    parsed.markdown.write_text('tampered', encoding='utf-8')
    with pytest.raises(MineruExtractionError, match='integrity'):
        cache.parse(pdf)
    assert fake.calls == 1


def test_process_death_releases_parse_lock_and_allows_retry(tmp_path: Path) -> None:
    pdf = tmp_path / 'paper.pdf'
    pdf.write_bytes(VALID_PDF)
    cache = MineruCache(tmp_path / 'cache', runner=FakeMineruRunner())
    child = subprocess.run([sys.executable, '-c', '''
import os
import sys
from pathlib import Path
from acquire_research_papers.mineru import MineruCache
def interrupted(pdf, entry):
    (entry / 'interrupted.txt').write_text('started', encoding='utf-8')
    os._exit(17)
MineruCache(Path(sys.argv[2]), runner=interrupted).parse(Path(sys.argv[1]))
''', str(pdf), str(cache.root)], capture_output=True, text=True, timeout=15)
    assert child.returncode == 17
    entry = cache.root / cache.key_for(pdf)
    assert (entry / 'interrupted.txt').read_text(encoding='utf-8') == 'started'

    result = cache.parse(pdf)

    assert result.markdown.read_text(encoding='utf-8') == '# Parsed paper\n'
    assert not (entry / 'parse.lock').exists()


def test_concurrent_parse_is_rejected_and_lock_released_after_failure(tmp_path: Path) -> None:
    pdf = tmp_path / 'paper.pdf'
    pdf.write_bytes(VALID_PDF)
    other = MineruCache(tmp_path / 'cache', runner=FakeMineruRunner())
    def interrupted(pdf, entry):
        with pytest.raises(MineruExtractionError, match='already being parsed'):
            other.parse(pdf)
        raise RuntimeError('synthetic runner failure')
    cache = MineruCache(tmp_path / 'cache', runner=interrupted)

    with pytest.raises(RuntimeError, match='synthetic runner failure'):
        cache.parse(pdf)

    assert other.parse(pdf).markdown.is_file()


def test_active_process_holds_lock_until_terminated(tmp_path: Path) -> None:
    pdf = tmp_path / 'paper.pdf'
    pdf.write_bytes(VALID_PDF)
    cache = MineruCache(tmp_path / 'cache', runner=FakeMineruRunner())
    entry = cache.root / cache.key_for(pdf)
    child = subprocess.Popen([sys.executable, '-c', '''
import sys
import time
from pathlib import Path
from acquire_research_papers.mineru import MineruCache
def waiting(pdf, entry):
    (entry / 'ready.txt').write_text('ready', encoding='utf-8')
    time.sleep(30)
MineruCache(Path(sys.argv[2]), runner=waiting).parse(Path(sys.argv[1]))
''', str(pdf), str(cache.root)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 10
        while not (entry / 'ready.txt').exists() and child.poll() is None:
            assert time.monotonic() < deadline, 'child parser did not acquire its lock'
            time.sleep(0.01)
        assert child.poll() is None
        with pytest.raises(MineruExtractionError, match='already being parsed'):
            cache.parse(pdf)
    finally:
        child.terminate()
        child.communicate(timeout=10)

    assert cache.parse(pdf).markdown.is_file()


def test_legacy_lock_blocks_cache_hits_without_modifying_lock_or_cache(tmp_path: Path) -> None:
    pdf = tmp_path / 'paper.pdf'
    pdf.write_bytes(VALID_PDF)
    cache = MineruCache(tmp_path / 'cache', runner=FakeMineruRunner())
    result = cache.parse(pdf)
    entry = result.output_dir.parent
    metadata = (entry / 'metadata.json').read_bytes()
    legacy = entry / 'parse.lock'
    legacy.write_text('other-process', encoding='utf-8')

    with pytest.raises(MineruExtractionError, match='legacy.*parse.lock'):
        cache.parse(pdf)

    assert legacy.read_text(encoding='utf-8') == 'other-process'
    assert (entry / 'metadata.json').read_bytes() == metadata


def test_legacy_cache_without_markdown_hash_is_preserved_and_not_reparsed(tmp_path: Path) -> None:
    pdf = tmp_path / 'paper.pdf'
    pdf.write_bytes(VALID_PDF)
    fake = FakeMineruRunner()
    cache = MineruCache(tmp_path / 'cache', runner=fake)
    result = cache.parse(pdf)
    metadata_path = result.output_dir.parent / 'metadata.json'
    metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
    del metadata['markdown_sha256']
    metadata_path.write_text(json.dumps(metadata), encoding='utf-8')
    original = metadata_path.read_bytes()

    with pytest.raises(MineruExtractionError, match='integrity'):
        cache.parse(pdf)

    assert fake.calls == 1
    assert metadata_path.read_bytes() == original
    assert result.markdown.read_text(encoding='utf-8') == '# Parsed paper\n'


def test_purge_skips_active_advisory_parse_and_can_remove_it_after_release(tmp_path: Path) -> None:
    pdf = tmp_path / 'paper.pdf'
    pdf.write_bytes(VALID_PDF)
    fake = FakeMineruRunner()
    cache = None
    def work(pdf, entry):
        result = fake(pdf, entry)
        metadata = {'last_accessed': (datetime.now(UTC) - timedelta(days=8)).isoformat()}
        (entry / 'metadata.json').write_text(json.dumps(metadata), encoding='utf-8')
        assert cache.purge_expired() == []
        assert result.markdown.is_file()
        return result
    cache = MineruCache(tmp_path / 'cache', runner=work)
    cache.parse(pdf)

    assert cache.purge_expired(now=datetime.now(UTC) + timedelta(days=8)) == [cache.key_for(pdf)]
