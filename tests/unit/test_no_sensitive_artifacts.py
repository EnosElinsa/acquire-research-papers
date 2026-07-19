import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def tracked_files() -> list[str]:
    return subprocess.check_output(
        ["git", "ls-files"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
    ).splitlines()


def test_repository_contains_no_runtime_or_delivery_artifacts() -> None:
    forbidden_suffixes = {".clixml", ".sqlite", ".pdf", ".bib", ".docx"}
    forbidden_parts = {
        "node_modules",
        ".venv",
        "browser-profiles",
        "downloads",
        "docs",
        "runs",
    }
    tracked = tracked_files()
    assert not [path for path in tracked if Path(path).suffix.casefold() in forbidden_suffixes]
    assert not [path for path in tracked if forbidden_parts.intersection(Path(path).parts)]


def test_skill_routes_all_three_modes_and_explicit_markdown_policy() -> None:
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "fetch" in text
    assert "discover corpus" in text
    assert "discover research" in text
    assert "Markdown" in text and "explicit" in text
    assert len(text.splitlines()) < 500


def test_progressive_disclosure_references_exist() -> None:
    required = {
        "corpus-mode.md",
        "research-mode.md",
        "source-policies.md",
        "credentials-and-cache.md",
    }
    reference_root = ROOT / "references"
    assert required == {path.name for path in reference_root.glob("*.md")}


def test_public_documentation_is_present_and_has_no_placeholders() -> None:
    public_files = [
        ROOT / "README.md",
        ROOT / "README.zh-CN.md",
        ROOT / "SECURITY.md",
        ROOT / "SKILL.md",
        *(ROOT / "references").glob("*.md"),
    ]
    assert all(path.is_file() for path in public_files)
    placeholder = re.compile(r"\b(?:TODO|TBD|FIXME|XXX)\b|\[TODO", re.IGNORECASE)
    assert not [path for path in public_files if placeholder.search(path.read_text(encoding="utf-8"))]


def test_tracked_text_contains_no_jwt_or_private_key() -> None:
    jwt = re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}")
    private_key = "-----BEGIN " + "PRIVATE KEY-----"
    offenders = []
    for relative in tracked_files():
        path = ROOT / relative
        if not path.is_file() or path.suffix.casefold() in {".png", ".jpg", ".zip"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if jwt.search(text) or private_key in text:
            offenders.append(relative)
    assert not offenders


def test_bundled_skill_validator_accepts_repository() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate_skill.py"), str(ROOT)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr or result.stdout
